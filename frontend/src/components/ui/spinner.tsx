import * as React from "react";
import { cn } from "@/lib/utils";

export const Spinner = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div
      ref={ref}
      className={cn("inline-block h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent text-muted-foreground", className)}
      role="status"
      aria-label="Loading"
      {...props}
    />
  ),
);
Spinner.displayName = "Spinner";
