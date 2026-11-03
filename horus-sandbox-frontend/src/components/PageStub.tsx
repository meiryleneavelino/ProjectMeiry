import type { ReactNode } from "react";

interface Props {
  title: string;
  description: string;
  children?: ReactNode;
}

export default function PageStub({ title, description, children }: Props) {
  return (
    <div>
      <h2 className="mb-1 font-serif text-xl font-semibold">{title}</h2>
      <p className="mb-5 max-w-xl text-sm text-ink-faint">{description}</p>
      {children ?? (
        <div className="rounded-card border border-dashed border-line bg-white p-8 text-center text-sm text-ink-faint">
          This screen has not been implemented yet. Start here — the layout in{" "}
          <code className="rounded bg-paper px-1 py-0.5">src/pages/Dashboard.tsx</code> is a good
          starting point for reusing the components in{" "}
          <code className="rounded bg-paper px-1 py-0.5">src/components</code>.
        </div>
      )}
    </div>
  );
}
