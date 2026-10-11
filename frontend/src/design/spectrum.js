/** Hue token for the n-th source (1-based). The spectrum has five hues and then repeats. */
export const sourceHue = (n) => `var(--p-s${((n - 1) % 5) + 1})`
