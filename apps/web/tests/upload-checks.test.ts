import { formatBytes, MAX_UPLOAD_BYTES, precheckFile } from "@/lib/upload-checks";

describe("precheckFile", () => {
  it.each([
    [{ name: "catalog.xlsx", size: 2048 }, null],
    [{ name: "CATALOG.CSV", size: 10 }, null],
    [{ name: "catalog.xlsm", size: 10 }, "Macro-enabled workbooks are not accepted. Save the file as .xlsx."],
    [{ name: "catalog.xls", size: 10 }, "Old .xls files are not supported. Save the file as .xlsx."],
    [{ name: "catalog.pdf", size: 10 }, "Upload a .csv or .xlsx file."],
    [{ name: "empty.csv", size: 0 }, "The file is empty."],
    [{ name: "big.csv", size: MAX_UPLOAD_BYTES + 1 }, "The file is larger than the 10 MB limit."],
  ])("%o -> %s", (file, expected) => {
    expect(precheckFile(file)).toBe(expected);
  });
});

describe("formatBytes", () => {
  it("uses readable units", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(2048)).toBe("2.0 KB");
    expect(formatBytes(3 * 1024 * 1024)).toBe("3.0 MB");
  });
});
