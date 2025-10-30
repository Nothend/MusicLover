// ID3Writer 将在需要时动态导入

/**
 * A robust class for writing metadata to FLAC files by rebuilding the metadata section.
 * This avoids complex and error-prone in-place modification of the binary data.
 */
class FLACMetadata {
    // Helper to read a 24-bit big-endian integer from a DataView.
    static _read_uint24_be(view, offset) {
        return (view.getUint8(offset) << 16) | (view.getUint8(offset + 1) << 8) | view.getUint8(offset + 2);
    }

    // Helper to write a 24-bit big-endian integer to a DataView.
    static _write_uint24_be(view, offset, value) {
        view.setUint8(offset, (value >> 16) & 0xff);
        view.setUint8(offset + 1, (value >> 8) & 0xff);
        view.setUint8(offset + 2, value & 0xff);
    }

    /**
     * Adds metadata to a FLAC file by rebuilding it.
     * @param {ArrayBuffer} arrayBuffer - The original FLAC file buffer.
     * @param {object} metadata - The metadata to add.
     * @returns {Promise<Blob>} A new Blob containing the FLAC file with updated metadata.
     */
    static async addMetadata(arrayBuffer, metadata) {
        const originalView = new DataView(arrayBuffer);

        if (originalView.getUint32(0) !== 0x664C6143) { // "fLaC"
            throw new Error('Invalid FLAC file: "fLaC" marker not found.');
        }

        // 1. Find all existing metadata blocks and the start of the audio frames.
        const existingBlocks = [];
        let offset = 4;
        let audioFramesOffset = -1;

        while (offset < originalView.byteLength) {
            const header = originalView.getUint8(offset);
            const isLast = (header & 0x80) !== 0;
            const type = header & 0x7f;
            const size = this._read_uint24_be(originalView, offset + 1);
            const blockEndOffset = offset + 4 + size;

            if (blockEndOffset > originalView.byteLength) {
                throw new Error("Found corrupted metadata block.");
            }

            existingBlocks.push({
                type: type,
                data: new Uint8Array(arrayBuffer, offset + 4, size)
            });

            if (isLast) {
                audioFramesOffset = blockEndOffset;
                break;
            }
            offset = blockEndOffset;
        }

        if (audioFramesOffset === -1) {
            throw new Error("Could not find the end of the metadata section (last block flag not set).");
        }

        // 2. Prepare a new list of blocks, keeping non-comment/picture blocks.
        const newBlocks = existingBlocks.filter(block => block.type !== 4 && block.type !== 6);

        // 3. Create and add the new VORBIS_COMMENT block.
        const vorbisComment = this._createVorbisComment({
            TITLE: metadata.title || '',
            ARTIST: metadata.artist || '',
            ALBUM: metadata.album || '',
            DATE: metadata.year || '',
            LYRICS: metadata.lyrics || ''
        });
        newBlocks.push({ type: 4, data: vorbisComment });

        // 4. Create and add the new PICTURE block if a cover is provided.
        if (metadata.cover) {
            const pictureBlock = await this._createPictureBlock(metadata.cover);
            newBlocks.push({ type: 6, data: pictureBlock });
        }

        // 5. Assemble the new metadata section from the new block list.
        let newMetadataSize = newBlocks.reduce((sum, block) => sum + 4 + block.data.byteLength, 0);
        const newMetadataBuffer = new ArrayBuffer(newMetadataSize);
        const newMetadataView = new DataView(newMetadataBuffer);
        const newMetadataBytes = new Uint8Array(newMetadataBuffer);
        let writeOffset = 0;

        for (let i = 0; i < newBlocks.length; i++) {
            const block = newBlocks[i];
            const isLastBlock = (i === newBlocks.length - 1);
            
            newMetadataView.setUint8(writeOffset, block.type | (isLastBlock ? 0x80 : 0x00));
            this._write_uint24_be(newMetadataView, writeOffset + 1, block.data.byteLength);
            newMetadataBytes.set(block.data, writeOffset + 4);
            
            writeOffset += 4 + block.data.byteLength;
        }

        // 6. Concatenate "fLaC" header, new metadata, and original audio frames.
        const audioFrames = new Uint8Array(arrayBuffer, audioFramesOffset);
        const newFileBytes = new Uint8Array(4 + newMetadataSize + audioFrames.byteLength);
        
        newFileBytes.set(new Uint8Array(arrayBuffer, 0, 4), 0); // "fLaC"
        newFileBytes.set(newMetadataBytes, 4);
        newFileBytes.set(audioFrames, 4 + newMetadataSize);

        return new Blob([newFileBytes], { type: 'audio/flac' });
    }

    static _createVorbisComment(tags) {
        const vendor = 'MusicParser';
        const vendorBytes = new TextEncoder().encode(vendor);
        const comments = Object.entries(tags).filter(([, value]) => value).map(([key, value]) => new TextEncoder().encode(`${key}=${value}`));
        
        let totalSize = 4 + vendorBytes.length + 4 + comments.reduce((sum, c) => sum + 4 + c.length, 0);
        const buffer = new ArrayBuffer(totalSize);
        const view = new DataView(buffer);
        let offset = 0;

        view.setUint32(offset, vendorBytes.length, true); offset += 4;
        new Uint8Array(buffer).set(vendorBytes, offset); offset += vendorBytes.length;
        
        view.setUint32(offset, comments.length, true); offset += 4;
        
        for (const comment of comments) {
            view.setUint32(offset, comment.length, true); offset += 4;
            new Uint8Array(buffer).set(comment, offset); offset += comment.length;
        }
        return new Uint8Array(buffer);
    }

    static async _createPictureBlock(coverBlob) {
        const imgData = await coverBlob.arrayBuffer();
        const mimeBytes = new TextEncoder().encode(coverBlob.type || 'image/jpeg');
        const descBytes = new TextEncoder().encode('Cover');
        
        const totalSize = 4 + 4 + mimeBytes.length + 4 + descBytes.length + 4 + 4 + 4 + 4 + 4 + imgData.byteLength;
        const buffer = new ArrayBuffer(totalSize);
        const view = new DataView(buffer);
        let offset = 0;

        view.setUint32(offset, 3, false); offset += 4; // type: front cover
        view.setUint32(offset, mimeBytes.length, false); offset += 4;
        new Uint8Array(buffer).set(mimeBytes, offset); offset += mimeBytes.length;
        
        view.setUint32(offset, descBytes.length, false); offset += 4;
        new Uint8Array(buffer).set(descBytes, offset); offset += descBytes.length;

        view.setUint32(offset, 0, false); offset += 4; // width
        view.setUint32(offset, 0, false); offset += 4; // height
        view.setUint32(offset, 24, false); offset += 4; // color depth
        view.setUint32(offset, 0, false); offset += 4; // indexed colors
        view.setUint32(offset, imgData.byteLength, false); offset += 4;
        new Uint8Array(buffer).set(new Uint8Array(imgData), offset);

        return new Uint8Array(buffer);
    }
}

/**
 * Embeds metadata into an audio file buffer.
 * @param {ArrayBuffer} audioBuffer The original audio file buffer.
 * @param {object} metadata The metadata to embed.
 * @param {string} fileExtension '.mp3' or '.flac'.
 * @returns {Promise<ArrayBuffer>} A new audio file buffer with embedded metadata.
 */
export async function embedMetadata(audioBuffer, metadata, fileExtension) {
    let coverBuffer;
    let coverMimeType = 'image/jpeg'; // Default MIME type

    if (metadata.cover) {
        try {
            const response = await fetch(metadata.cover);
            if (!response.ok) throw new Error(`Failed to fetch cover image: ${response.statusText}`);
            coverMimeType = response.headers.get('content-type') || coverMimeType;
            coverBuffer = await response.arrayBuffer();
        } catch (e) {
            console.error("Could not fetch cover image, skipping. Error:", e.message);
        }
    }

    if (fileExtension === '.mp3') {
        // 动态导入ID3Writer以减少初始包大小
        const { ID3Writer } = await import('browser-id3-writer');
        const writer = new ID3Writer(audioBuffer);
        writer.setFrame('TIT2', metadata.name)
              .setFrame('TPE1', [metadata.artist])
              .setFrame('TALB', metadata.album)
              .setFrame('TYER', metadata.year);
        
        if (metadata.lyrics) {
            writer.setFrame('USLT', {
                description: 'Lyrics',
                lyrics: metadata.lyrics
            });
        }
        if (coverBuffer) {
            writer.setFrame('APIC', {
                type: 3,
                data: coverBuffer,
                description: 'Cover',
                mime: coverMimeType
            });
        }
        writer.addTag();
        return writer.arrayBuffer;
    }

    if (fileExtension === '.flac') {
        try {
            const flacMetadata = {
                title: metadata.name,
                artist: metadata.artist,
                album: metadata.album,
                year: metadata.year,
                lyrics: metadata.lyrics,
            };
            if (coverBuffer) {
                flacMetadata.cover = new Blob([coverBuffer], { type: coverMimeType });
            }
            const modifiedBlob = await FLACMetadata.addMetadata(audioBuffer, flacMetadata);
            return await modifiedBlob.arrayBuffer();
        } catch (error) {
            console.error('Failed to embed FLAC metadata:', error);
            return audioBuffer; // Return original buffer on failure
        }
    }

    console.warn(`Unsupported file extension for metadata embedding: ${fileExtension}`);
    return audioBuffer;
}