import { neon } from '@neondatabase/serverless';

let sqlInstance: ReturnType<typeof neon> | null = null;

export function getSql() {
  const url = process.env.NEON_DATABASE_URL;
  if (!url) {
    throw new Error('NEON_DATABASE_URL must be a Neon postgres connection string');
  }

  if (!sqlInstance) {
    sqlInstance = neon(url);
  }

  return sqlInstance;
}