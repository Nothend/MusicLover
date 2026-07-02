/*
 * 浏览器端音频标签注入器 —— 前端下载时给音频写入元信息（标题/艺人/专辑/年份/音轨号/歌词/封面）。
 *
 * 本项目采用纯前端下载：音频字节本就已在浏览器内存里（fetch → Blob），因此在生成 Blob 前
 * 对字节做一次标签注入即可，服务端完全不碰音频。
 *
 * 覆盖格式：
 *   - FLAC：解析 metadata block 序列，替换 VORBIS_COMMENT(4) 与 PICTURE(6)，不触碰音频帧。
 *   - MP3 ：在文件头写 ID3v2.4（UTF-8 编码），剥离原有 ID3v2 后前置新标签。
 *   - 其它（m4a 等）：原样返回，不处理。
 *
 * 注意字节序：FLAC block header 长度是 24 位大端；VORBIS_COMMENT 内部长度是 32 位【小端】；
 * PICTURE 内部字段是 32 位大端；ID3v2.4 的标签/帧长度是 syncsafe（每字节 7 位）。
 */
(function () {
    'use strict';

    const enc = new TextEncoder(); // UTF-8

    // ---- 小工具：整数打包 + 拼接 ----
    const u32be = (n) => new Uint8Array([(n >>> 24) & 255, (n >>> 16) & 255, (n >>> 8) & 255, n & 255]);
    const u32le = (n) => new Uint8Array([n & 255, (n >>> 8) & 255, (n >>> 16) & 255, (n >>> 24) & 255]);
    const u24be = (n) => new Uint8Array([(n >>> 16) & 255, (n >>> 8) & 255, n & 255]);
    // ID3v2.4 的 syncsafe 整数：28 位分装进 4 字节，每字节仅用低 7 位
    const syncsafe = (n) => new Uint8Array([(n >>> 21) & 0x7f, (n >>> 14) & 0x7f, (n >>> 7) & 0x7f, n & 0x7f]);

    function concat(chunks) {
        let len = 0;
        for (const c of chunks) len += c.length;
        const out = new Uint8Array(len);
        let off = 0;
        for (const c of chunks) { out.set(c, off); off += c.length; }
        return out;
    }

    const hasText = (v) => v !== undefined && v !== null && String(v).length > 0;

    // 归一化封面 MIME：去掉参数、修正网易返回的非标准 image/jpg → image/jpeg
    function normMime(m) {
        m = (m || 'image/jpeg').split(';')[0].trim().toLowerCase();
        return m === 'image/jpg' ? 'image/jpeg' : m;
    }

    // ==================== FLAC ====================
    function buildVorbisComment(meta) {
        const vendor = enc.encode('musiclover');
        const comments = [];
        const add = (k, v) => { if (hasText(v)) comments.push(enc.encode(k + '=' + v)); };
        add('TITLE', meta.title);
        (meta.artists || []).forEach((a) => { if (a) comments.push(enc.encode('ARTIST=' + a)); });
        add('ALBUM', meta.album);
        add('DATE', meta.year);          // 发行年份
        add('TRACKNUMBER', meta.trackNumber);
        add('LYRICS', meta.lyrics);
        const parts = [u32le(vendor.length), vendor, u32le(comments.length)];
        comments.forEach((c) => { parts.push(u32le(c.length)); parts.push(c); });
        return concat(parts);
    }

    function buildFlacPicture(meta) {
        const mime = enc.encode(normMime(meta.coverMime));
        const desc = enc.encode('');
        return concat([
            u32be(3),                        // 图片类型 3 = 封面(front cover)
            u32be(mime.length), mime,
            u32be(desc.length), desc,
            u32be(0), u32be(0), u32be(0), u32be(0), // 宽/高/色深/用色数：未知填 0
            u32be(meta.coverBytes.length), meta.coverBytes,
        ]);
    }

    function writeFlac(bytes, meta) {
        // 校验 "fLaC" 魔数
        if (!(bytes[0] === 0x66 && bytes[1] === 0x4c && bytes[2] === 0x61 && bytes[3] === 0x43)) return bytes;

        let pos = 4;
        const kept = []; // 保留的原始块（STREAMINFO 等）
        while (pos + 4 <= bytes.length) {
            const header = bytes[pos];
            const isLast = (header & 0x80) !== 0;
            const type = header & 0x7f;
            const len = (bytes[pos + 1] << 16) | (bytes[pos + 2] << 8) | bytes[pos + 3];
            const dataStart = pos + 4;
            const data = bytes.subarray(dataStart, dataStart + len);
            pos = dataStart + len;
            // 丢弃旧的 VORBIS_COMMENT(4)/PICTURE(6)/PADDING(1)，其余（含 STREAMINFO=0）保留原顺序
            if (type !== 4 && type !== 6 && type !== 1) kept.push({ type, data });
            if (isLast) break;
        }
        const audio = bytes.subarray(pos); // 音频帧，原样保留

        const blocks = kept.slice();
        blocks.push({ type: 4, data: buildVorbisComment(meta) });
        if (meta.coverBytes && meta.coverBytes.length) blocks.push({ type: 6, data: buildFlacPicture(meta) });

        const out = [bytes.subarray(0, 4)]; // "fLaC"
        blocks.forEach((b, i) => {
            const lastFlag = i === blocks.length - 1 ? 0x80 : 0x00; // 最后一个 metadata 块置标志位
            out.push(new Uint8Array([lastFlag | b.type]));
            out.push(u24be(b.data.length));
            out.push(b.data);
        });
        out.push(audio);
        return concat(out);
    }

    // ==================== MP3 / ID3v2.4 ====================
    // 帧 = 4字节ID + syncsafe(4) 长度 + 2字节标志(0) + body
    function id3Frame(id, body) {
        return concat([enc.encode(id), syncsafe(body.length), new Uint8Array([0x00, 0x00]), body]);
    }

    function writeMp3(bytes, meta) {
        // 剥离已有 ID3v2（网易 mp3 可能自带），新标签整体前置
        let audioStart = 0;
        if (bytes[0] === 0x49 && bytes[1] === 0x44 && bytes[2] === 0x33) { // "ID3"
            const size = (bytes[6] << 21) | (bytes[7] << 14) | (bytes[8] << 7) | bytes[9]; // syncsafe
            audioStart = 10 + size;
            if (bytes[5] & 0x10) audioStart += 10; // 存在 footer 再加 10
        }
        const audio = bytes.subarray(audioStart);

        const frames = [];
        const textFrame = (id, text) => {
            if (!hasText(text)) return;
            frames.push(id3Frame(id, concat([new Uint8Array([0x03]), enc.encode(String(text))]))); // 0x03 = UTF-8
        };
        textFrame('TIT2', meta.title);
        textFrame('TPE1', (meta.artists || []).filter(Boolean).join('/'));
        textFrame('TALB', meta.album);
        textFrame('TDRC', meta.year);          // 发行年份（v2.4 允许仅年份）
        textFrame('TRCK', meta.trackNumber);

        if (hasText(meta.lyrics)) {
            // USLT: enc(1) + lang(3) + 内容描述(null 结尾) + 歌词
            frames.push(id3Frame('USLT', concat([
                new Uint8Array([0x03]), enc.encode('und'), new Uint8Array([0x00]), enc.encode(meta.lyrics),
            ])));
        }
        if (meta.coverBytes && meta.coverBytes.length) {
            const mime = enc.encode(normMime(meta.coverMime));
            // APIC: enc(1) + MIME(null结尾) + 图片类型(1) + 描述(null结尾) + 图片数据
            frames.push(id3Frame('APIC', concat([
                new Uint8Array([0x03]), mime, new Uint8Array([0x00]),
                new Uint8Array([0x03]), new Uint8Array([0x00]), meta.coverBytes,
            ])));
        }

        const framesBuf = concat(frames);
        const header = concat([enc.encode('ID3'), new Uint8Array([0x04, 0x00, 0x00]), syncsafe(framesBuf.length)]);
        return concat([header, framesBuf, audio]);
    }

    // ==================== 入口 ====================
    // arrayBuffer: 原始音频（ArrayBuffer 或 Uint8Array）；fileType: 'flac'/'mp3'/...；meta: 见 buildVorbisComment
    // 返回：写好标签的 Uint8Array（不支持的格式或出错时原样返回）
    function writeTags(arrayBuffer, fileType, meta) {
        const bytes = arrayBuffer instanceof Uint8Array ? arrayBuffer : new Uint8Array(arrayBuffer);
        try {
            const fmt = (fileType || '').toLowerCase();
            if (fmt === 'flac') return writeFlac(bytes, meta || {});
            if (fmt === 'mp3') return writeMp3(bytes, meta || {});
            return bytes; // m4a 等：原样返回
        } catch (e) {
            console.warn('[AudioTagger] 写入标签失败，返回原始音频', e);
            return bytes;
        }
    }

    // 浏览器挂到 window；node 测试时挂到 module.exports
    if (typeof window !== 'undefined') window.AudioTagger = { writeTags };
    if (typeof module !== 'undefined' && module.exports) module.exports = { writeTags };
})();
