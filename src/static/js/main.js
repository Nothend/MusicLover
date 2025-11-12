// 调整原Flask模板路径为相对路径（关键修改）
import { embedMetadata } from '/static/js/metadataWriter.js';

// 所有DOM操作代码包裹在DOMContentLoaded事件中
document.addEventListener('DOMContentLoaded', function() {
    // 全局变量
    let playlistData = null;
    let currentPage = 1;
    const pageSize = 30;
    let isBatchDownloading = false;
    let isFromPlaylistParse = false; // 标记是否从歌单解析进入单首歌曲视图
    const activeXhrs = new Map(); // 存储活跃请求的Map
    
    // 侧边栏控制
    const settingsSidebar = document.getElementById('settings-sidebar');
    const openSettingsBtn = document.getElementById('openSettings');
    const closeSettingsBtn = document.getElementById('closeSettings');
    const sidebarContent = document.getElementById('sidebar-content');
    
    function openSidebar() {
        settingsSidebar.style.width = '350px';
        document.body.style.overflow = 'hidden';
        if (sidebarContent) {
            sidebarContent.scrollTop = 0; // 重置滚动位置
            sidebarContent.style.display = 'none';
            sidebarContent.offsetHeight; // 触发重绘
            sidebarContent.style.display = 'block';
        }
    }
    
    function closeSidebar() {
        settingsSidebar.style.width = '0';
        document.body.style.overflow = '';
    }
    
    openSettingsBtn.addEventListener('click', openSidebar);
    closeSettingsBtn.addEventListener('click', closeSidebar);
    
    document.addEventListener('click', (e) => {
        const isClickInside = settingsSidebar.contains(e.target);
        const isOpenButton = openSettingsBtn.contains(e.target);
        
        if (!isClickInside && !isOpenButton && settingsSidebar.style.width !== '0px') {
            closeSidebar();
        }
    });
    
    // 二维码生成功能
    const generateBtn = document.getElementById('generate-qr-btn');
    const qrImage = document.getElementById('qr-code-image');
    const qrPlaceholder = document.getElementById('qr-placeholder');
    const loginStatus = document.getElementById('login-status');
    const scanResult = document.getElementById('scan-result');
    const copyBtn = document.getElementById('copy-cookie-btn');
    const clearBtn = document.getElementById('clear-cookie-btn');
    const countdownDisplay = document.getElementById('countdown-display');
    
    // 状态变量
    let qrKey = null;
    let checkInterval = null;
    let countdownInterval = null;
    const MAX_CHECK_COUNT = 60; // 3分钟（3秒/次 × 60次）
    let checkCount = 0;
    let remainingSeconds = 180; // 180秒 = 3分钟
    
    if (generateBtn){
        generateBtn.addEventListener('click', function() {
            resetQrState();
            
            fetch('/api/qr/generate')
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        qrKey = data.data.qr_key;
                        qrImage.src = `data:image/png;base64,${data.data.qr_base64}`;
                        qrImage.style.display = 'block';
                        qrPlaceholder.style.display = 'none';
                        updateStatus('请使用网易云音乐APP扫描二维码', 'info');
                        startCountdown();
                        startCheckingStatus();
                    } else {
                        updateStatus(`生成失败: ${data.message}`, 'danger');
                    }
                })
                .catch(error => {
                    console.error('生成二维码失败:', error);
                    updateStatus('生成二维码时发生错误', 'danger');
                });
        });
    };
    
    function startCountdown() {
        remainingSeconds = 180;
        updateCountdownDisplay();
        
        countdownInterval = setInterval(() => {
            remainingSeconds--;
            updateCountdownDisplay();
            
            if (remainingSeconds <= 0) {
                clearInterval(countdownInterval);
                clearInterval(checkInterval);
                updateStatus('二维码已过期，请重新生成', 'danger');
                qrImage.style.opacity = '0.5';
                qrImage.style.filter = 'grayscale(100%)';
                qrImage.style.border = '2px solid #f44336';
                
                const expiredWatermark = document.createElement('div');
                expiredWatermark.id = 'qr-expired-watermark';
                expiredWatermark.style.position = 'absolute';
                expiredWatermark.style.top = '50%';
                expiredWatermark.style.left = '50%';
                expiredWatermark.style.transform = 'translate(-50%, -50%)';
                expiredWatermark.style.color = '#f44336';
                expiredWatermark.style.fontWeight = 'bold';
                expiredWatermark.style.fontSize = '1.2rem';
                expiredWatermark.style.textShadow = '0 0 3px white';
                expiredWatermark.style.pointerEvents = 'none';
                expiredWatermark.textContent = '已过期';
                
                const qrContainer = document.querySelector('.qr-code-container');
                qrContainer.style.position = 'relative';
                qrContainer.appendChild(expiredWatermark);
            }
        }, 1000);
    }
    
    function updateCountdownDisplay() {
        const minutes = Math.floor(remainingSeconds / 60);
        const seconds = remainingSeconds % 60;
        countdownDisplay.textContent = `${minutes}:${seconds.toString().padStart(2, '0')}`;
    }
    
    function startCheckingStatus() {
        if (!qrKey) return;
        
        checkCount = 0;
        checkInterval = setInterval(() => {
            if (checkCount >= MAX_CHECK_COUNT) {
                clearInterval(checkInterval);
                clearInterval(countdownInterval);
                updateStatus('二维码已过期', 'danger');
                return;
            }
            
            checkCount++;
            
            fetch(`/api/qr/check?qr_key=${encodeURIComponent(qrKey)}`)
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        updateStatus(data.data.message, getStatusColor(data.data.status_code));
                        
                        switch(data.data.status_code) {
                            case 803: // 登录成功
                                clearInterval(checkInterval);
                                clearInterval(countdownInterval);
                                scanResult.value = data.data.cookie || '获取Cookie失败';
                                qrImage.style.border = '2px solid #4caf50';
                                const isVip = data.data.is_vip;
                                if (isVip) {
                                    updateStatus('登录成功，您是VIP用户', 'success');
                                    showToast('登录成功，您是VIP用户', 'success');
                                } else {
                                    updateStatus('登录成功，但您当前不是VIP用户', 'warning');
                                    showToast('您当前不是VIP用户，就别费劲了', 'warning');
                                }
                                break;
                            case 800: // 二维码已过期
                                clearInterval(checkInterval);
                                clearInterval(countdownInterval);
                                qrImage.style.opacity = '0.5';
                                break;
                        }
                    } else {
                        updateStatus(`检查失败: ${data.message}`, 'danger');
                        stopAllIntervals();
                    }
                })
                .catch(error => {
                    console.error('检查登录状态失败:', error);
                    updateStatus('检查状态时发生错误', 'danger');
                    stopAllIntervals();
                });
        }, 3000);
    }
    
    function updateStatus(message, type) {
        loginStatus.textContent = message;
        loginStatus.className = `badge badge-${type}`;
    }
    
    function getStatusColor(statusCode) {
        switch(statusCode) {
            case 801: return 'info';
            case 802: return 'warning';
            case 803: return 'success';
            case 800: return 'danger';
            default: return 'secondary';
        }
    }
    
    if (copyBtn) {
        copyBtn.addEventListener('click', function() {
            if (scanResult.value) {
                scanResult.select();
                document.execCommand('copy');
                updateStatus('Cookie已复制到剪贴板', 'success');
            } else {
                updateStatus('没有可复制的内容', 'warning');
            }
        });
    }
    
    if (clearBtn) {
        clearBtn.addEventListener('click', function() {
            resetQrState();
        });
    };
    
    function resetQrState() {
        stopAllIntervals();
        
        const expiredWatermark = document.getElementById('qr-expired-watermark');
        if (expiredWatermark) {
            expiredWatermark.remove();
        }
        
        qrImage.src = '';
        qrImage.style.display = 'none';
        qrImage.style.opacity = '1';
        qrImage.style.filter = 'none';
        qrImage.style.border = 'none';
        qrPlaceholder.style.display = 'block';
        loginStatus.textContent = '';
        loginStatus.className = '';
        scanResult.value = '';
        countdownDisplay.textContent = '3:00';
    }
    
    function stopAllIntervals() {
        if (checkInterval) {
            clearInterval(checkInterval);
            checkInterval = null;
        }
        if (countdownInterval) {
            clearInterval(countdownInterval);
            countdownInterval = null;
        }
    }
    
    // 支付方式切换
    const paymentMethod = document.getElementById('payment-method');
    const paymentQrImage = document.getElementById('payment-qr-image');
    
    paymentMethod.addEventListener('change', () => {
        if (paymentMethod.value === 'alipay') {
            paymentQrImage.src = "/static/alipay.png"; // 相对路径
            paymentQrImage.alt = '支付宝收款码';
        } else {
            paymentQrImage.src = "/static/wechat.png"; // 相对路径
            paymentQrImage.alt = '微信收款码';
        }
    });

    // 密码验证功能
    const passwordInput = document.getElementById('qr-password');
    const verifyButton = document.getElementById('verify-password');
    const passwordError = document.getElementById('password-error');
    const passwordContainer = document.getElementById('password-container');
    const qrFeatureContainer = document.getElementById('qr-feature-container');

    verifyButton.addEventListener('click', verifyPassword);
    passwordInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            verifyPassword();
        }
    });

    function verifyPassword() {
        const password = passwordInput.value.trim();
        
        if (!password) {
            showError('请输入密码');
            return;
        }
        
        fetch(`/api/check-password?password=${encodeURIComponent(password)}`)
            .then(response => {
                if (!response.ok) {
                    throw new Error(`请求失败: ${response.status}`);
                }
                return response.json();
            })
            .then(data => {
                if (data.success) {
                    localStorage.setItem('qrFeatureVerified', 'true');
                    showQrFeatures();
                } else {
                    showError('密码错误，请重试');
                    passwordInput.value = '';
                }
            })
            .catch(error => {
                console.error('密码验证失败:', error);
                showError('验证失败，请检查网络或服务器');
            });
    }

    function showQrFeatures() {
        passwordContainer.style.opacity = '0';
        setTimeout(() => {
            passwordContainer.style.display = 'none';
            qrFeatureContainer.style.display = 'block';
            setTimeout(() => {
                qrFeatureContainer.style.opacity = '1';
            }, 50);
        }, 300);
    }

    function showError(message) {
        if (!passwordError) return;
        passwordError.textContent = message;
        passwordError.classList.add('visible');
        
        passwordInput.style.animation = 'none';
        passwordInput.offsetHeight;
        passwordInput.style.animation = 'shake 0.5s';
        
        setTimeout(() => {
            passwordError.classList.remove('visible');
            passwordInput.style.animation = '';
        }, 3000);
    }

    // DOM元素
    const parseOptions = document.querySelectorAll('.parse-option');
    const parseTitle = document.getElementById('parse-title');
    const inputLabel = document.getElementById('input-label');
    const parseInput = document.getElementById('parse-input');
    const resultCard = document.getElementById('result-card');
    const playlistResult = document.getElementById('playlist-result');
    const singleResult = document.getElementById('single-result');
    const backToPlaylistContainer = document.getElementById('back-to-playlist-container');
    const backToPlaylistBtn = document.getElementById('back-to-playlist');
    const bigPicModal = document.getElementById('bigPicModal');
    const bigPicImg = document.getElementById('big-pic-img');
    const closeBigPic = document.getElementById('closeBigPic');
    const showBigPicBtn = document.getElementById('show-big-pic');
    
    // 解析方式选择事件
    parseOptions.forEach(option => {
        option.addEventListener('click', () => {
            parseOptions.forEach(opt => opt.classList.remove('active'));
            option.classList.add('active');
            
            const type = option.getAttribute('data-type');
            parseTitle.textContent = type;
            inputLabel.textContent = type;
            
            switch(type) {
                case '链接解析':
                    parseInput.placeholder = '请输入音乐链接';
                    break;
                case '歌单解析':
                    parseInput.placeholder = '请输入歌单链接';
                    break;
                case '专辑解析':
                    parseInput.placeholder = '请输入专辑链接';
                    break;
            }
            
            if (type === '歌单解析' && playlistData) {
                resultCard.style.display = 'block';
                singleResult.style.display = 'none';
                playlistResult.style.display = 'block';
                backToPlaylistContainer.style.display = 'none';
                isFromPlaylistParse = false;
            } else {
                resultCard.style.display = 'none';
            }
        });
    });
    
    // 默认选中第一个选项
    parseOptions[1].click();
    
    // 音质选择下拉菜单
    const qualityDisplay = document.getElementById('quality-display');
    const qualityOptions = document.getElementById('quality-options');
    const qualitySelect = document.getElementById('quality-select');
    const qualityItems = document.querySelectorAll('#quality-options .select-option');
    
    qualityDisplay.addEventListener('click', () => {
        qualityOptions.style.display = qualityOptions.style.display === 'block' ? 'none' : 'block';
    });
    
    document.addEventListener('click', (e) => {
        if (!qualityDisplay.contains(e.target) && !qualityOptions.contains(e.target)) {
            qualityOptions.style.display = 'none';
        }
    });
    
    qualityItems.forEach(item => {
        item.addEventListener('click', () => {
            qualityItems.forEach(i => i.classList.remove('active'));
            item.classList.add('active');
            
            const qualityName = item.querySelector('span:first-child').textContent;
            const value = item.getAttribute('data-value');
            
            qualityDisplay.innerHTML = `
                <span>${qualityName}</span>
                <span>▼</span>
            `;
            qualitySelect.value = value;
            qualityOptions.style.display = 'none';
        });
    });

    // 格式化时长（毫秒转分:秒）
    function formatDuration(ms) {
        if (!ms) return '未知';
        const totalSeconds = Math.floor(ms / 1000);
        const minutes = Math.floor(totalSeconds / 60);
        const seconds = totalSeconds % 60;
        return `${minutes}:${seconds.toString().padStart(2, '0')}`;
    }

    // 格式化时间（时间戳转日期）
    function formatDate(timestamp) {
        if (!timestamp) return '未知';
        const date = new Date(timestamp);
        return date.toLocaleString('zh-CN', {
            year: 'numeric',
            month: '2-digit',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit'
        });
    }

    // 获取音质文本
    function getQualityText(level) {
        const qualityMap = {
            'standard': '标准音质',
            'exhigh': '极高音质',
            'lossless': '无损音质',
            'hires': 'Hi-Res音质',
            'sky': '沉浸环绕声',
            'jyeffect': '高清环绕声',
            'jymaster': '超清母带'
        };
        return qualityMap[level] || level;
    }

    /**
     * 单首歌曲下载函数
     */
    function downloadSingleSong(songId, quality, songName, songItemEl) {
        return new Promise((resolve) => {
            const progressContainer = songItemEl.querySelector('.song-progress');
            progressContainer.style.display = 'block';
            const progressBar = progressContainer.querySelector('.progress-bar');
            progressBar.style.width = '0%';
            progressBar.style.background = '#4caf50';
            
            const statusContainer = songItemEl.querySelector('.download-status');
            statusContainer.innerHTML = '<span class="badge badge-downloading">下载中</span>';

            const xhr = new XMLHttpRequest();
            xhr.open('POST', '/Download', true);
            xhr.setRequestHeader('Content-Type', 'application/x-www-form-urlencoded');
            xhr.responseType = 'blob';
            xhr.timeout = 600000;

            xhr.ontimeout = function() {
                clearInterval(progressInterval);
                progressBar.style.width = '100%';
                progressBar.style.background = '#f44336';
                statusContainer.innerHTML = '<span class="badge badge-failed">下载超时</span>';
                resolve(false);
            };

            let progressInterval;
            let simulatedProgress = 0;
            progressInterval = setInterval(() => {
                if (simulatedProgress < 90) {
                    simulatedProgress += 0.3;
                    progressBar.style.width = simulatedProgress + '%';
                }
            }, 1000);
            
            xhr.onload = function() {
                clearInterval(progressInterval);
                
                if (xhr.status === 200) {
                    progressBar.style.width = '100%';
                    statusContainer.innerHTML = '<span class="badge badge-success">已下载</span>';
                    
                    const encodedFilename = xhr.getResponseHeader('X-Download-Filename') || 
                                        xhr.getResponseHeader('Content-Disposition')?.match(/filename\*=UTF-8''(.*)/)?.[1];
                    const filename = encodedFilename ? decodeURIComponent(encodedFilename) : `${songName}.${quality === 'lossless' ? 'flac' : 'mp3'}`;
                    
                    const blob = xhr.response;
                    const url = window.URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = filename;
                    document.body.appendChild(a);
                    a.click();
                    document.body.removeChild(a);
                    window.URL.revokeObjectURL(url);
                    
                    resolve(true);
                } else {
                    progressBar.style.width = '100%';
                    progressBar.style.background = '#f44336';
                    statusContainer.innerHTML = '<span class="badge badge-failed">下载失败</span>';
                    resolve(false);
                }
            };
            
            xhr.onerror = function() {
                clearInterval(progressInterval);
                progressBar.style.width = '100%';
                progressBar.style.background = '#f44336';
                statusContainer.innerHTML = '<span class="badge badge-failed">下载失败</span>';
                resolve(false);
            };
            
            const formData = `id=${encodeURIComponent(songId)}&quality=${encodeURIComponent(quality)}&format=file`;
            xhr.send(formData);
        });
    }

    
    // 解析处理方法 - 链接解析
    function parseSingleSongHandler(id) {
        return new Promise((resolve, reject) => {
            console.log('[链接解析] 开始处理，歌曲ID：', id);
            const button = document.getElementById('parse-button');
            
            const level = document.getElementById('quality-select').value;
            const xhr = new XMLHttpRequest();
            xhr.open('POST', '/Song_V1', true);
            xhr.setRequestHeader('Content-Type', 'application/x-www-form-urlencoded');
            
            xhr.onload = function() {
                if (xhr.status === 200) {
                    try {
                        const data = JSON.parse(xhr.responseText);
                        if (data.status === 200) {
                            resultCard.style.display = 'block';
                            playlistResult.style.display = 'none';
                            singleResult.style.display = 'block';
                            
                            if (isFromPlaylistParse) {
                                backToPlaylistContainer.style.display = 'block';
                            } else {
                                backToPlaylistContainer.style.display = 'none';
                            }

                            document.getElementById('download_id').value = id;
                            document.getElementById('download_quality').value = level;

                            const navInfo = data.data.in_navidrome || {};
                            const titleWithFlag = navInfo.exists 
                                ? `${data.data.name} <span style="color: #f44336; font-size: 0.8rem; margin-left: 5px;">已在库中</span>`
                                : data.data.name;
                            document.getElementById('single-song-title').innerHTML = titleWithFlag;

                            let navDetails = '';
                            if (navInfo.exists) {
                                navDetails = `<span style="font-size: 0.8rem; margin-left: 5px; background: #e3f2fd; padding: 2px 6px; border-radius: 3px; color: #666;">[库内: ${navInfo.artists || '未知'} - ${navInfo.album || '未知'}]</span>`;
                            }
                            document.getElementById('single-song-artist').innerHTML = `${data.data.ar_name} ${navDetails}`;

                            document.getElementById('single-album').textContent = data.data.al_name;
                            document.getElementById('single-duration').textContent = formatDuration(data.data.duration);

                            const qualityText = getQualityText(data.data.level);
                            const qualityWithMP3 = navInfo.is_mp3 
                                ? `${qualityText} <span style="color: #f44336; font-size: 0.8rem;">MP3</span>`
                                : qualityText;
                            document.getElementById('single-quality').innerHTML = qualityWithMP3;

                            document.getElementById('single-size').textContent = data.data.size || '未知';
                            showBigPicBtn.setAttribute('data-pic', data.data.pic);

                            const container = document.getElementById('aplayer-container');
                            container.innerHTML = '';
                            let downloadUrl = data.data.url;
                            const currentProtocol = window.location.protocol;

                            if (currentProtocol === 'https:' && downloadUrl.startsWith('http://')) {
                                downloadUrl = downloadUrl.replace('http://', 'https://');
                                console.log('HTTPS环境下自动替换链接:', downloadUrl);
                            }
                            new APlayer({
                                container: container,
                                lrcType: 0,
                                audio: [{
                                    name: data.data.name,
                                    artist: data.data.ar_name,
                                    url: downloadUrl,
                                    cover: data.data.pic
                                }]
                            });

                            resolve();
                        } else {
                            showToast(data.data.msg || '解析失败，请重试', 'error');
                            reject(new Error(data.data.msg || '解析失败'));
                        }
                    } catch (e) {
                        showToast('解析响应数据失败', 'error');
                        reject(e);
                    }
                } else {
                    showToast(`请求失败，状态码: ${xhr.status}`, 'error');
                    reject(new Error(`请求失败，状态码: ${xhr.status}`));
                }
            };
            
            xhr.onerror = function() {
                showToast('解析请求失败: 网络错误', 'error');
                reject(new Error('解析请求失败: 网络错误'));
            };
            
            const formData = `url=${encodeURIComponent(id)}&level=${encodeURIComponent(level)}&type=json`;
            xhr.send(formData);
        });
    }

    // 渲染当前页歌曲列表
    function renderCurrentPageSongs() {
        if (!playlistData) return;
        
        const isPlaylist = !!playlistData.data.playlist;
        const mainData = isPlaylist 
            ? playlistData.data.playlist 
            : playlistData.data.album;
        
        const allSongs = mainData.songs || mainData.tracks || [];
        const totalSongs = mainData.songCount || mainData.trackCount || allSongs.length;
        const totalPages = Math.ceil(totalSongs / pageSize);
        
        if (allSongs.length === 0) {
            document.getElementById('song-list').innerHTML = 
                `<div style="padding: 20px; text-align: center; color: #666;">未获取到歌曲数据</div>`;
            return;
        }
        
        document.getElementById('playlist-stats').textContent = 
            `共${totalSongs}首（第${currentPage}页，共${totalPages}页，每页${pageSize}首）`;
        
        const startIndex = (currentPage - 1) * pageSize;
        const endIndex = Math.min(startIndex + pageSize, allSongs.length);
        const currentSongs = allSongs.slice(startIndex, endIndex);
        
        const songList = document.getElementById('song-list');
        songList.innerHTML = '';
        
        currentSongs.forEach(function(song, idx) {
            const actualIndex = startIndex + idx + 1;
            const navInfo = song.in_navidrome || {};
            let navBadges = '';
            
            if (navInfo.exists) {
                navBadges += '<span class="badge badge-success">库内</span>';
                if (navInfo.is_mp3) {
                    navBadges += '<span class="badge badge-warning">MP3</span>';
                }
            }
            
            const songName = song.name || song.songName || '未知歌曲';
            const artists = song.artists || song.ar_name || '未知歌手';
            const album = song.album || song.albumName || '未知专辑';
            const picUrl = song.picUrl || song.coverImgUrl || '';
            const songId = song.id || song.songId || '';
            
            const songItem = document.createElement('div');
            songItem.className = 'song-item';
            songItem.setAttribute('data-id', songId);
            songItem.innerHTML = `
                <div class="song-index">${actualIndex}</div>
                <div class="song-info">
                    <div>
                        <img src="${picUrl}" alt="封面">
                        <strong>${songName}</strong>
                        <span style="font-size: 0.9rem; color: #666; margin-left: 5px;">
                            [${artists} - ${album}]
                        </span>
                        ${navBadges}
                        <span class="download-status"></span>
                    </div>
                    <div class="song-progress">
                        <div class="progress-bar-container">
                            <div class="progress-bar" role="progressbar" style="width: 0%"></div>
                        </div>
                    </div>
                </div>
                <div class="song-actions">
                    <button class="parse-song-btn btn btn-primary" 
                            data-id="${songId}" data-name="${songName}" style="padding: 5px 10px; font-size: 0.9rem;">
                        解析
                    </button>
                </div>
            `;
            
            const parseBtn = songItem.querySelector('.parse-song-btn');
            parseBtn.addEventListener('click', () => {
                requireValidCookie(() => {
                    isFromPlaylistParse = true;
                    parseSingleSongHandler(songId);
                });
            });
            
            songList.appendChild(songItem);
        });
        
        document.getElementById('prev-page').disabled = currentPage === 1;
        document.getElementById('next-page').disabled = currentPage === totalPages;
        renderPageNumbers(totalPages);
    }
    
    // 渲染页码
    function renderPageNumbers(totalPages) {
        const pageNumbersContainer = document.getElementById('page-numbers');
        pageNumbersContainer.innerHTML = '';
        
        let startPage = Math.max(1, currentPage - 4);
        let endPage = Math.min(totalPages, startPage + 9);
        
        if (endPage - startPage < 9 && startPage > 1) {
            startPage = Math.max(1, endPage - 9);
        }
        
        for (let i = startPage; i <= endPage; i++) {
            const pageBtn = document.createElement('button');
            pageBtn.className = `page-item ${i === currentPage ? 'active' : ''}`;
            pageBtn.textContent = i;
            pageBtn.addEventListener('click', () => {
                currentPage = i;
                renderCurrentPageSongs();
            });
            pageNumbersContainer.appendChild(pageBtn);
        }
    }
    
    // 解析处理方法 - 歌单解析
    function parsePlaylistHandler(id) {
        console.log('[歌单解析] 开始处理，歌单ID：', id);
        const button = document.getElementById('parse-button');
        const originalText = button.innerHTML;
        
        button.disabled = true;
        button.innerHTML = '<span class="loading"></span> 解析中...';

        const xhr = new XMLHttpRequest();
        xhr.open('GET', `/Playlist?id=${encodeURIComponent(id)}`, true);
        
        xhr.onload = function() {
            button.disabled = false;
            button.innerHTML = originalText;

            if (xhr.status === 200) {
                try {
                    const data = JSON.parse(xhr.responseText);
                    console.log('歌单接口返回数据:', data);
                    
                    if (data.status === 200) {
                        playlistData = data;
                        currentPage = 1;
                        
                        const pl = data.data.playlist;
                        const totalSongs = pl.songCount || pl.trackCount || 0;
                        
                        resultCard.style.display = 'block';
                        singleResult.style.display = 'none';
                        playlistResult.style.display = 'block';
                        backToPlaylistContainer.style.display = 'none';

                        const creator = pl.creator || pl.author || '未知创作者';
                        const createTime = pl.createTime || pl.create_time || null;
                        document.getElementById('playlist-meta').textContent = 
                            `创建者：${creator}  •  歌曲数：${totalSongs}  •  创建时间：${formatDate(createTime)}`;
                        
                        renderCurrentPageSongs();
                    } else {
                        resultCard.style.display = 'block';
                        singleResult.style.display = 'none';
                        playlistResult.style.display = 'block';
                        document.getElementById('song-list').innerHTML = 
                            `<div style="padding: 20px; text-align: center; color: #666;">歌单解析失败：${data.data.msg || '未知错误'}</div>`;
                        document.getElementById('pagination').style.display = 'none';
                    }
                } catch (e) {
                    showToast('解析歌单数据失败', 'error');
                    console.error(e);
                }
            } else {
                showToast(`歌单请求失败，状态码: ${xhr.status}`, 'error');
            }
        };
        
        xhr.onerror = function() {
            button.disabled = false;
            button.innerHTML = originalText;
            showToast('歌单解析请求失败: 网络错误', 'error');
        };
        
        xhr.send();
    }

    // 解析处理方法 - 专辑解析
    function parseAlbumHandler(id) {
        console.log('[专辑解析] 开始处理，专辑ID：', id);
        const button = document.getElementById('parse-button');
        const originalText = button.innerHTML;
        
        button.disabled = true;
        button.innerHTML = '<span class="loading"></span> 解析中...';

        const xhr = new XMLHttpRequest();
        xhr.open('GET', `/Album?id=${encodeURIComponent(id)}`, true);
        
        xhr.onload = function() {
            button.disabled = false;
            button.innerHTML = originalText;

            if (xhr.status === 200) {
                try {
                    const data = JSON.parse(xhr.responseText);
                    console.log('专辑接口返回数据:', data);
                    
                    if (data.status === 200) {
                        playlistData = data;
                        currentPage = 1;
                        
                        const album = data.data.album;
                        const totalSongs = album.songs ? album.songs.length : 0;
                        
                        resultCard.style.display = 'block';
                        singleResult.style.display = 'none';
                        playlistResult.style.display = 'block';
                        backToPlaylistContainer.style.display = 'none';

                        const publishTime = album.publishTime ? formatDate(album.publishTime) : '未知';
                        document.getElementById('playlist-meta').textContent = 
                            `专辑名称：${album.name}  •  艺术家：${album.artist}  •  发行时间：${publishTime}  •  歌曲数：${totalSongs}`;
                        
                        renderCurrentPageSongs();
                    } else {
                        resultCard.style.display = 'block';
                        singleResult.style.display = 'none';
                        playlistResult.style.display = 'block';
                        document.getElementById('song-list').innerHTML = 
                            `<div style="padding: 20px; text-align: center; color: #666;">专辑解析失败：${data.data.msg || '未知错误'}</div>`;
                        document.getElementById('pagination').style.display = 'none';
                    }
                } catch (e) {
                    showToast('解析专辑数据失败', 'error');
                    console.error(e);
                }
            } else {
                showToast(`请求失败，状态码: ${xhr.status}`, 'error');
            }
        };
        
        xhr.onerror = function() {
            button.disabled = false;
            button.innerHTML = originalText;
            showToast('专辑解析请求失败: 网络错误', 'error');
        };
        
        xhr.send();
    }

    // 单首歌曲下载按钮事件
    document.getElementById('download-btn').addEventListener('click', async function() {
        const musicId = document.getElementById('download_id').value.trim();
        const quality = document.getElementById('download_quality').value;
        const songName = document.getElementById('single-song-title').textContent.trim();
        
        if (!musicId) {
            showToast('请先解析音乐获取信息', 'info');
            return;
        }

        const progressContainer = document.getElementById('download-progress');
        progressContainer.style.display = 'block';
        const progressBar = progressContainer.querySelector('.progress-bar');
        progressBar.style.width = '0%';
        progressBar.style.background = '#42a5f5';

        const downloadBtn = document.getElementById('download-btn');
        downloadBtn.disabled = true;
        downloadBtn.innerHTML = '<span class="loading"></span> 下载中...';

        const success = await clientDownloadSingleSong(
            musicId, 
            quality, 
            songName, 
            {
                querySelector: (selector) => {
                    if (selector === '.song-progress') return progressContainer;
                    if (selector === '.download-status') return { innerHTML: '' };
                    return null;
                }
            }
        );

        downloadBtn.disabled = false;
        downloadBtn.innerHTML = '下载音乐';
        if (!success) {
            progressBar.style.background = '#f44336';
        }
    });
    
    // 批量下载按钮事件
    document.getElementById('batchDownloadBtn').addEventListener('click', () => {
        requireValidCookie(clientFastDownload);
    });
    
    // 返回歌单列表按钮事件
    backToPlaylistBtn.addEventListener('click', () => {
        if (playlistData) {
            singleResult.style.display = 'none';
            playlistResult.style.display = 'block';
            backToPlaylistContainer.style.display = 'none';
            isFromPlaylistParse = false;
            playlistResult.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
    });
    
    // 分页控制事件
    document.getElementById('prev-page').addEventListener('click', () => {
        if (currentPage > 1) {
            currentPage--;
            renderCurrentPageSongs();
        }
    });
    
    document.getElementById('next-page').addEventListener('click', () => {
        if (playlistData) {
            const pl = playlistData.data.playlist;
            const totalSongs = pl.songCount || pl.trackCount || (pl.songs || pl.tracks || []).length;
            const totalPages = Math.ceil(totalSongs / pageSize);
            if (currentPage < totalPages) {
                currentPage++;
                renderCurrentPageSongs();
            }
        }
    });
    
    // 提取ID从URL
    function extractIdFromUrl(input, type) {
        let id = '';
        if (input.includes('http')) {
            if (type === '链接解析' && (input.includes('song') || input.includes('music.163.com'))) {
                const match = input.match(/song\?id=(\d+)/) || input.match(/\/(\d+)\//);
                if (match && match[1]) id = match[1];
            } else if (type === '歌单解析' && input.includes('playlist')) {
                const match = input.match(/playlist\?id=(\d+)/);
                if (match && match[1]) id = match[1];
            } else if (type === '专辑解析' && input.includes('album')) {
                const match = input.match(/album\?id=(\d+)/);
                if (match && match[1]) id = match[1];
            }
        }
        
        if (!id && /^\d+$/.test(input.trim())) {
            id = input.trim();
        }
        
        return id;
    };
    
    // 解析按钮点击事件
    document.getElementById('parse-button').addEventListener('click', () => {
        const input = parseInput.value.trim();
        const activeParseOption = document.querySelector('.parse-option.active');
        const type = activeParseOption ? activeParseOption.getAttribute('data-type') : '链接解析';

        if (!input) {
            parseInput.style.borderColor = '#f44336';
            setTimeout(() => parseInput.style.borderColor = '#ddd', 1000);
            return;
        }

        const id = extractIdFromUrl(input, type);
        if (!id) {
            showToast('无法从输入中提取有效的ID，请检查输入是否正确', 'error');
            return;
        }

        isFromPlaylistParse = false;
        
        switch (type) {
            case '链接解析':
                parseSingleSongHandler(id);
                break;
            case '歌单解析':
                parsePlaylistHandler(id);
                break;
            case '专辑解析':
                parseAlbumHandler(id);
                break;
            default:
                console.log('未知解析类型：', type);
        }
    });
    
    // 支持回车键解析
    parseInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            document.getElementById('parse-button').click();
        }
    });

    // 检查Cookie是否有效
    async function checkCookieValidity() {
        try {
            const response = await fetch('/api/check-cookie');
            const data = await response.json();
            
            return {
                success: data.success,
                valid: data.data?.valid || false,
                isVip: data.data?.is_vip || false
            };
        } catch (error) {
            console.error('检查Cookie有效性失败:', error);
            return { success: false, valid: false, isVip: false };
        }
    };

    // 需要Cookie验证的操作前调用
    async function requireValidCookie(action) {
        const { success, valid, isVip } = await checkCookieValidity();

        if (!success) {
            showToast('Cookie验证失败，请稍后重试', 'error');
            openSidebar();
            return false;
        }
        
        if (!valid) {
            showToast('Cookie无效或已过期，请先在设置中扫码登录', 'warning');
            openSidebar();
            return false;
        }
        
        if (!isVip) {
            showToast('您不是VIP用户，无法执行此操作', 'warning');
            return false;
        }
        
        action();
        return true;
    };
    
    // 显示大图
    showBigPicBtn.addEventListener('click', () => {
        const picUrl = showBigPicBtn.getAttribute('data-pic');
        if (picUrl) {
            bigPicImg.src = picUrl;
            bigPicModal.style.display = 'flex';
        }
    });
    
    // 关闭大图
    closeBigPic.addEventListener('click', () => {
        bigPicModal.style.display = 'none';
    });
    
    bigPicModal.addEventListener('click', (e) => {
        if (e.target === bigPicModal) {
            bigPicModal.style.display = 'none';
        }
    });

    // 提示框功能
    function showToast(message, type = 'info', duration = 3000) {
        let container = document.querySelector('.toast-container');
        if (!container) {
            container = document.createElement('div');
            container.className = 'toast-container';
            document.body.appendChild(container);
        }
        
        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        toast.textContent = message;
        container.appendChild(toast);
        
        setTimeout(() => toast.classList.add('show'), 10);
        
        setTimeout(() => {
            toast.classList.remove('show');
            setTimeout(() => toast.remove(), 300);
        }, duration);
    }
});