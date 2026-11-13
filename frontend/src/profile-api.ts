export interface ProfileData {
  skills: string[];
  target_titles: string[];
  location: string;
  work_preferences: ('remote' | 'hybrid' | 'onsite')[];
}

export const exampleProfile: ProfileData = {
  skills: ['Project planning', 'Budgeting', 'Stakeholder communication'],
  target_titles: ['Operations Manager', 'Program Coordinator'],
  location: 'Example City',
  work_preferences: ['remote', 'hybrid'],
};

export function parseProfile(value: unknown): ProfileData {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error(
      'Choose a JSON object containing skills, target_titles, location, and work_preferences.',
    );
  }
  const profile = value as Record<string, unknown>;
  if (Object.keys(profile).sort().join(',') !== 'location,skills,target_titles,work_preferences') {
    throw new Error(
      'JSON must contain exactly skills, target_titles, location, and work_preferences.',
    );
  }
  function strings(key: string, maxItems: number, maxLength: number): string[] {
    const values = profile[key];
    if (
      !Array.isArray(values) ||
      values.length < 1 ||
      values.length > maxItems ||
      values.some(
        (value) => typeof value !== 'string' || !value.trim() || value.trim().length > maxLength,
      )
    ) {
      throw new Error(
        `${key}: enter 1–${maxItems} nonempty items, up to ${maxLength} characters each.`,
      );
    }
    return values.map((value) => value.trim());
  }
  const skills = strings('skills', 50, 100);
  const titles = strings('target_titles', 20, 120);
  const preferences = strings('work_preferences', 3, 10);
  if (preferences.some((value) => !['remote', 'hybrid', 'onsite'].includes(value))) {
    throw new Error('Work preferences must be remote, hybrid, or onsite.');
  }
  if (
    typeof profile.location !== 'string' ||
    !profile.location.trim() ||
    profile.location.trim().length > 160
  ) {
    throw new Error('Enter a location between 1 and 160 characters.');
  }
  return {
    skills,
    target_titles: titles,
    location: profile.location.trim(),
    work_preferences: preferences as ProfileData['work_preferences'],
  };
}

export async function readProfile(): Promise<ProfileData | null> {
  const response = await fetch('/api/profile', { signal: AbortSignal.timeout(15000) });
  if (response.status === 404) return null;
  if (!response.ok)
    throw new Error('Your saved profile could not be loaded. Try again when the API is available.');
  return parseProfile(await response.json());
}

export async function saveProfile(profile: ProfileData): Promise<ProfileData> {
  const response = await fetch('/api/profile', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(profile),
    signal: AbortSignal.timeout(15000),
  });
  if (!response.ok)
    throw new Error(
      response.status === 422
        ? 'The profile was rejected. Check your skills, titles, location, and work preferences.'
        : 'The save could not be confirmed. Your edits are still here; try saving again.',
    );
  return parseProfile(await response.json());
}
