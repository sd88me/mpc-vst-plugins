/* Built-in programs of this project's own (the instrument's factory programs are not shipped; load your own .syx banks). */
#pragma once
#include <stdint.h>
int presets_count(void);
void presets_apply(int k, uint8_t *patch, char name[17]);   /* patch already holds the init values */
