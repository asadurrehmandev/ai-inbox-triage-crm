"use client";

import { ThemeProvider } from "next-themes";
import { CommandBusProvider } from "@/components/command-bus";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { DeskProvider } from "@/components/use-desk";
import { SessionKeyProvider } from "@/components/session-key";

export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <ThemeProvider attribute="class" defaultTheme="light" enableSystem disableTransitionOnChange>
      <SessionKeyProvider>
        <TooltipProvider delayDuration={400}>
          <DeskProvider>
            <CommandBusProvider>
              {children}
              <Toaster />
            </CommandBusProvider>
          </DeskProvider>
        </TooltipProvider>
      </SessionKeyProvider>
    </ThemeProvider>
  );
}
