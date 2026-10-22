"use client";

import * as React from "react";
import { Tabs as TabsPrimitive } from "radix-ui";
import { cn } from "@/lib/utils";

function Tabs(props: React.ComponentProps<typeof TabsPrimitive.Root>) {
  return <TabsPrimitive.Root {...props} />;
}

function TabsList({ className, ...props }: React.ComponentProps<typeof TabsPrimitive.List>) {
  return (
    <TabsPrimitive.List
      className={cn("flex flex-nowrap items-center gap-1", className)}
      {...props}
    />
  );
}

function TabsTrigger({ className, ...props }: React.ComponentProps<typeof TabsPrimitive.Trigger>) {
  return (
    <TabsPrimitive.Trigger
      className={cn(
        "inline-flex h-8 items-center gap-1.5 rounded-md px-2 text-sm text-muted-foreground outline-none hover:bg-muted data-[state=active]:bg-background data-[state=active]:text-foreground data-[state=active]:shadow-[inset_0_0_0_1px_var(--border)] max-md:min-h-11",
        className,
      )}
      {...props}
    />
  );
}

export { Tabs, TabsList, TabsTrigger };
