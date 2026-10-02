/* Reads the framebuffer an active DRM CRTC is scanning out and writes "W H PITCH FOURCC MODIFIER\n" + raw pixels to
 * stdout. Read-only: GETRESOURCES/GETCRTC/GETFB2, export the buffer as a dma-buf and mmap it PROT_READ. */
#include <drm.h>
#include <drm_mode.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <unistd.h>
#include <linux/dma-buf.h>

int main(int argc, char **argv) {
    const char *dev = argc > 1 ? argv[1] : "/dev/dri/card1";
    int fd = open(dev, O_RDWR | O_CLOEXEC);
    if (fd < 0) { perror(dev); return 1; }
    struct drm_mode_card_res r = {0};
    if (ioctl(fd, DRM_IOCTL_MODE_GETRESOURCES, &r)) { perror("GETRESOURCES"); return 1; }
    uint32_t crtcs[16];
    if (r.count_crtcs > 16) r.count_crtcs = 16;
    struct drm_mode_card_res r2 = {0};
    r2.crtc_id_ptr = (uintptr_t)crtcs; r2.count_crtcs = r.count_crtcs;
    if (ioctl(fd, DRM_IOCTL_MODE_GETRESOURCES, &r2)) { perror("GETRESOURCES2"); return 1; }
    for (unsigned i = 0; i < r2.count_crtcs; i++) {
        struct drm_mode_crtc c = {0};
        c.crtc_id = crtcs[i];
        if (ioctl(fd, DRM_IOCTL_MODE_GETCRTC, &c) || !c.fb_id) continue;
        struct drm_mode_fb_cmd2 f = {0};
        f.fb_id = c.fb_id;
        if (ioctl(fd, DRM_IOCTL_MODE_GETFB2, &f)) { perror("GETFB2"); continue; }
        fprintf(stderr, "crtc %u fb %u %ux%u fmt %.4s pitch %u off %u mod %llx handle %u\n", c.crtc_id, f.fb_id, f.width, f.height,
                (char *)&f.pixel_format, f.pitches[0], f.offsets[0], (unsigned long long)f.modifier[0], f.handles[0]);
        if (!f.handles[0]) { fprintf(stderr, "no handle (need root)\n"); return 1; }
        struct drm_prime_handle p = {.handle = f.handles[0], .flags = DRM_CLOEXEC};
        if (ioctl(fd, DRM_IOCTL_PRIME_HANDLE_TO_FD, &p)) { perror("PRIME"); return 1; }
        size_t len = (size_t)f.pitches[0] * f.height + f.offsets[0];
        uint8_t *px = mmap(NULL, len, PROT_READ, MAP_SHARED, p.fd, 0);
        if (px == MAP_FAILED) { perror("mmap"); return 1; }
        struct dma_buf_sync s = {.flags = DMA_BUF_SYNC_START | DMA_BUF_SYNC_READ};
        ioctl(p.fd, DMA_BUF_IOCTL_SYNC, &s);
        printf("%u %u %u %.4s %llx\n", f.width, f.height, f.pitches[0], (char *)&f.pixel_format, (unsigned long long)f.modifier[0]);
        fwrite(px + f.offsets[0], 1, (size_t)f.pitches[0] * f.height, stdout);
        s.flags = DMA_BUF_SYNC_END | DMA_BUF_SYNC_READ;
        ioctl(p.fd, DMA_BUF_IOCTL_SYNC, &s);
        return 0;
    }
    fprintf(stderr, "no active crtc\n");
    return 1;
}
