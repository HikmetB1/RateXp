import { expect, it } from "vitest";
import { ratingsPerDay } from "../ui/app/dashboard/ratingsPerDay";

it("fills every day between the first and last rated one, zero where nobody rated", () => {
  const [good, bad] = ratingsPerDay([
    { day: "2026-10-01T00:00:00.000000000Z", good: "3", bad: "1" },
    { day: "2026-10-03T00:00:00.000000000Z", good: "2", bad: "0" },
  ]);
  expect(good.name).toBe("good");
  expect(good.datapoints.map((d) => d.value)).toEqual([3, 0, 2]);
  expect(bad.datapoints.map((d) => d.value)).toEqual([1, 0, 0]);
  expect(good.datapoints[1].start.toISOString()).toBe("2026-10-02T00:00:00.000Z");
  expect(good.datapoints[1].end.toISOString()).toBe("2026-10-03T00:00:00.000Z");
});

it("draws no datapoints without rows", () => {
  expect(ratingsPerDay([]).map((s) => s.datapoints)).toEqual([[], []]);
});
