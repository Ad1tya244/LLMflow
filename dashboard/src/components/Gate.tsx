import type { ReactNode } from "react";
import { useConnection } from "../lib/store";
import { Skeleton } from "./ui";

/** Pages render only for a signed-in user; App shows the sign-in screen otherwise. */
export function Gate({ children }: { children: ReactNode }) {
  const { auth } = useConnection();
  if (auth === "signed_in") return <>{children}</>;
  return (
    <div className="panel panel-body stack" aria-busy>
      <Skeleton height={24} />
      <Skeleton height={160} />
    </div>
  );
}
