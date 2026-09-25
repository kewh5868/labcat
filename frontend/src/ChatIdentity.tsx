export function chatLabel(title: string, number?: number): string {
  return number === undefined ? title : `${title} · #${number}`;
}

/** The number identifies a saved chat; it never becomes part of its editable title. */
export default function ChatIdentity({
  title,
  number,
}: {
  title: string;
  number?: number;
}) {
  return (
    <span className="chat-identity" title={chatLabel(title, number)}>
      <span className="chat-identity-title">{title}</span>
      {number !== undefined && (
        <span className="chat-number">
          <span className="sr-only"> · </span>#{number}
        </span>
      )}
    </span>
  );
}
