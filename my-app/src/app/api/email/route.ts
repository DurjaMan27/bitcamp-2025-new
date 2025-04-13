import { getSql } from '../../db';
import { NextResponse } from 'next/server';
import { Email } from '../../types/types';

export async function GET() {
  const sql = getSql();
  const emails = await sql`SELECT * FROM public.emails`;

  return NextResponse.json(emails as Email[]);
}

export async function POST(request: Request) {
  const sql = getSql();
  const email: Email = await request.json();

  await sql`
    INSERT INTO public.emails (inbox_type, receiver, sender, time, subject, content, tag, reply)
    VALUES (${email.inbox_type}, ${email.receiver}, ${email.sender}, ${email.time}, ${email.subject}, ${email.content}, ${email.reply}, ${email.tag})
  `;

  return NextResponse.json({ message: 'Email uploaded' }, { status: 201 });
}