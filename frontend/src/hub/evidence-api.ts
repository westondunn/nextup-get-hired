import { request } from '../jobs-api';

export interface Evidence {
  id: string;
  seed_key: string | null;
  topic: string;
  detail: string;
  verification_status: string;
  source: string | null;
  scope: string | null;
  dates: string | null;
  personal_contribution: string;
  permitted_wording: string;
  instruction: string;
  created_at: string;
  updated_at: string;
}

export interface ResumeFile {
  name: string;
  type: string;
  size: number;
  uploaded_at: string;
}

export interface ResumeVersion {
  id: string;
  variant_name: string;
  content: string;
  version_number: number;
  is_active: boolean;
  notes: string;
  file: ResumeFile | null;
  created_at: string;
  updated_at: string;
}

export const RESUME_FILE_TYPES: Record<string, string> = {
  pdf: 'application/pdf',
  docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
};

const json = (method: string, value: unknown) => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(value),
});

export const readEvidence = (status?: string) =>
  request<Evidence[]>(`evidence${status ? `?verification_status=${status}` : ''}`);
export const createEvidence = (data: Record<string, unknown>) =>
  request<Evidence>('evidence', json('POST', data));
export const updateEvidence = (id: string, data: Record<string, unknown>) =>
  request<Evidence>(`evidence/${id}`, json('PUT', data));
export const deleteEvidence = (id: string) => request<void>(`evidence/${id}`, { method: 'DELETE' });

export const readResumes = () => request<ResumeVersion[]>('resumes');
export const createResume = (data: Record<string, unknown>) =>
  request<ResumeVersion>('resumes', json('POST', data));
export const updateResume = (id: string, data: Record<string, unknown>) =>
  request<ResumeVersion>(`resumes/${id}`, json('PUT', data));
export const newResumeVersion = (id: string) =>
  request<ResumeVersion>(`resumes/${id}/new-version`, { method: 'POST' });

export const resumeFileUrl = (id: string) => `/api/resumes/${id}/file`;
export const deleteResumeFile = (id: string) =>
  request<void>(`resumes/${id}/file`, { method: 'DELETE' });

/** Upload a PDF or DOCX; the type comes from the extension so browsers cannot mislabel it. */
export async function uploadResumeFile(id: string, file: File) {
  const extension = file.name.split('.').pop()?.toLowerCase() ?? '';
  const contentType = RESUME_FILE_TYPES[extension];
  if (!contentType) throw new Error('Upload a PDF or Word (.docx) file.');
  const bytes = new Uint8Array(await file.arrayBuffer());
  let binary = '';
  for (let i = 0; i < bytes.length; i += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  }
  return request<ResumeVersion>(
    `resumes/${id}/file`,
    json('PUT', { file_name: file.name, content_type: contentType, data_base64: btoa(binary) }),
  );
}
