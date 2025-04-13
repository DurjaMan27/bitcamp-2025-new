export interface Email {
  id: number;
  inbox_type: String;
  receiver: String;
  sender: String;
  time: String;
  subject: String;
  content: String;
  tag: String;
  reply: String;
}

export interface User {
  id: number;
  username: String;
  email: String;
}
