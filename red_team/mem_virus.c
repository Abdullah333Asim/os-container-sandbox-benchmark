#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <string.h>
#include <sys/prctl.h>

#define MAX_CHUNKS 40

int main(int argc, char *argv[]) {
    int gen = 1;
    if (argc == 3 && strcmp(argv[1], "--gen") == 0) { gen = atoi(argv[2]); }

    if (gen == 3) {
        prctl(PR_SET_NAME, "systemd-journal", 0, 0, 0);
    }

    void *chunks[MAX_CHUNKS];
    int allocated = 0;

    for (int i = 0; i < MAX_CHUNKS; i++) {
        chunks[i] = malloc(10 * 1024 * 1024);
        if (chunks[i]) {
            memset(chunks[i], 0xA5, 10 * 1024 * 1024);
            allocated += 10;
        }

        if (gen == 1) {
            usleep(10000);
        } else {
            usleep(400000);
        }
    }

    sleep(350);

    for (int i = 0; i < MAX_CHUNKS; i++) {
        if (chunks[i]) free(chunks[i]);
    }
    return 0;
}
