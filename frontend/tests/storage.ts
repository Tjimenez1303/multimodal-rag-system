/** Fill the tab's storage quota, so the browser refuses the next write. */
export function fillSessionStorage(): void {
  let index = 0;
  for (let size = 1024 * 1024; size >= 1; size = Math.floor(size / 2)) {
    const chunk = "x".repeat(size);
    for (;;) {
      try {
        sessionStorage.setItem(`filler-${index}`, chunk);
        index += 1;
      } catch {
        break;
      }
    }
  }
}
