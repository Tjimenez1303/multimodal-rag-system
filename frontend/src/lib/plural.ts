// The interface is in English (FR-042), so English plural rules apply.
const rules = new Intl.PluralRules("en");

/**
 * The form of an English noun that agrees with a count.
 *
 * @param count - How many things the noun refers to.
 * @param singular - The noun for one, such as "page".
 * @param plural - The noun for any other count, the singular plus "s" by default.
 * @returns "page" for 1, "pages" otherwise.
 */
export function nounFor(
  count: number,
  singular: string,
  plural = `${singular}s`,
): string {
  return rules.select(count) === "one" ? singular : plural;
}

/**
 * A count followed by the noun that agrees with it.
 *
 * @param count - How many things there are.
 * @param singular - The noun for one, such as "page".
 * @param plural - The noun for any other count, the singular plus "s" by default.
 * @returns "1 page", "3 pages".
 */
export function counted(
  count: number,
  singular: string,
  plural = `${singular}s`,
): string {
  return `${count} ${nounFor(count, singular, plural)}`;
}
