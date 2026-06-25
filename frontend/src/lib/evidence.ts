import { API_BASE_URL, EvidenceUpload } from "./api";

export function readFileAsBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ""));
    reader.onerror = () => reject(reader.error ?? new Error("Could not read file"));
    reader.readAsDataURL(file);
  });
}

export async function fileToEvidenceUpload(file: File): Promise<EvidenceUpload> {
  const data_base64 = await readFileAsBase64(file);
  return {
    file_name: file.name,
    content_type: file.type || "application/octet-stream",
    size: file.size,
    data_base64,
  };
}

export function evidenceImageUrl(evidenceId: string, token: string): string {
  return `${API_BASE_URL}/api/evidence/${encodeURIComponent(evidenceId)}?token=${encodeURIComponent(token)}`;
}

export function isImageEvidence(contentType?: string | null, filePath?: string): boolean {
  if (contentType?.startsWith("image/")) {
    return true;
  }
  return /\.(png|jpe?g|gif|webp|bmp)$/i.test(filePath ?? "");
}
