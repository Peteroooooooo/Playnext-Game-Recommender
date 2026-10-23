import { describe, expect, it } from "vitest";
import { EXAMPLES, addPart, removePart, splitParts } from "./guide";
import { DICTS } from "./i18n";

describe("guide chips", () => {
  it("trims a chip label before adding it", () => {
    expect(addPart("cozy", " on sale ", ", ")).toBe("cozy, on sale");
    expect(addPart("", " 两个人同屏 ", "，")).toBe("两个人同屏");
  });

  it("adds a part with the language's separator", () => {
    expect(addPart("", "两个人同屏", "，")).toBe("两个人同屏");
    expect(addPart("想玩轻松的 ", "两个人同屏", "，")).toBe("想玩轻松的，两个人同屏");
    expect(addPart("something cozy", "on sale", ", ")).toBe("something cozy, on sale");
  });

  it("removes exactly that part and keeps the rest", () => {
    expect(removePart("想玩轻松的，两个人同屏，在打折的", "两个人同屏", "，")).toBe("想玩轻松的，在打折的");
    expect(removePart("something cozy, on sale", "on sale", ", ")).toBe("something cozy");
  });

  it("splits typed text the same way the chips join it", () => {
    expect(splitParts("a，b， c", "，")).toEqual(["a", "b", "c"]);
    expect(splitParts("a, b,c", ", ")).toEqual(["a", "b", "c"]);
  });
});

describe("guide text", () => {
  it("has one sentence and one game name per example in both languages", () => {
    for (const d of Object.values(DICTS)) {
      expect(d.examples).toHaveLength(EXAMPLES.length);
      expect(d.exGroups).toHaveLength(4);
      expect(d.parts[d.partNeedsLib]).toBeTruthy();
    }
    expect(new Set(EXAMPLES.map((e) => e.appid)).size).toBe(EXAMPLES.length);
  });
});
