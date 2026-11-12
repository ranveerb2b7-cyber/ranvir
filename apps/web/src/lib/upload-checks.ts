/** Client-side pre-checks for a quick, friendly error. The server re-validates everything. */
export const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;
const ALLOWED = [".csv", ".xlsx"];

export function precheckFile(file: { name: string; size: number }): string | null {
  const name = file.name.toLowerCase();
  if (name.endsWith(".xlsm")) return "Macro-enabled workbooks are not accepted. Save the file as .xlsx.";
  if (name.endsWith(".xls")) return "Old .xls files are not supported. Save the file as .xlsx.";
  if (!ALLOWED.some((ext) => name.endsWith(ext))) return "Upload a .csv or .xlsx file.";
  if (file.size === 0) return "The file is empty.";
  if (file.size > MAX_UPLOAD_BYTES) return "The file is larger than the 10 MB limit.";
  return null;
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
