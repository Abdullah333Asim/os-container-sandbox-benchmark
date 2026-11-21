#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <unistd.h>
#include <pthread.h>
#include <time.h>

static volatile int keep_running = 1;

static void *burn_worker(void *arg) {
    unsigned long seed = (unsigned long)(uintptr_t)arg + 1;
    volatile unsigned long acc = seed;
    while (keep_running) {
        for (int i = 0; i < 1000000; i++) {
            acc = (acc * 1664525UL + 1013904223UL) ^ (unsigned long)i;
        }
    }
    return (void *)(uintptr_t)acc;
}

int main(int argc, char *argv[]) {
    int threads = 4;
    int duration = 8;
    for (int i = 1; i + 1 < argc; i += 2) {
        if (strcmp(argv[i], "--threads") == 0) threads = atoi(argv[i + 1]);
        else if (strcmp(argv[i], "--sec") == 0) duration = atoi(argv[i + 1]);
    }
    if (threads < 1) threads = 1;
    if (threads > 16) threads = 16;

    pthread_t tids[16];
    for (int i = 0; i < threads; i++) {
        pthread_create(&tids[i], NULL, burn_worker, (void *)(uintptr_t)i);
    }
    sleep((unsigned int)duration);
    keep_running = 0;
    for (int i = 0; i < threads; i++) {
        pthread_join(tids[i], NULL);
    }
    printf("STRESS_DONE,threads=%d,sec=%d\n", threads, duration);
    return 0;
}
