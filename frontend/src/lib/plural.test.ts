import { counted, nounFor } from "@/lib/plural";

test.each([
  [0, "0 pages"],
  [1, "1 page"],
  [2, "2 pages"],
  [71, "71 pages"],
])("%i reads as %s", (count, text) => {
  expect(counted(count, "page")).toBe(text);
});

test("an irregular plural can be given", () => {
  expect(counted(1, "entry", "entries")).toBe("1 entry");
  expect(counted(3, "entry", "entries")).toBe("3 entries");
});

test("the noun alone follows the count", () => {
  expect(nounFor(1, "page")).toBe("page");
  expect(nounFor(4, "page")).toBe("pages");
});
