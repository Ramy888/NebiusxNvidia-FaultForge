import { plural, sentence } from "./text";

test("sentence capitalises the first letter only", () => {
  expect(sentence("the provider times out")).toBe("The provider times out");
});

test("plural handles one and many", () => {
  expect(plural(1, "line")).toBe("1 line");
  expect(plural(3, "line")).toBe("3 lines");
});
