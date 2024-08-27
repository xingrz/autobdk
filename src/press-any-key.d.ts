// declare module 'press-any-key';
declare module 'press-any-key' {
  export default function pressAnyKey(message?: string, options?: {
    ctrlC?: number | 'reject' | false,
    preverseLog?: boolean;
  }): Promise<void>;
}
