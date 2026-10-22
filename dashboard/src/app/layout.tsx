import type { Metadata } from "next";
import { Figtree, Newsreader } from "next/font/google";
import { SessionKeyProvider } from "@/components/session-key";
import "./globals.css";

const figtree = Figtree({
  variable: "--font-figtree",
  subsets: ["latin"],
});

const newsreader = Newsreader({
  variable: "--font-newsreader",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Lane · AI triage with human approval",
  description:
    "Runs out of the box in Demo mode with sample responses. Paste your own Anthropic or OpenAI key, never stored, to test the live AI. A person approves every lead before it reaches the CRM.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${figtree.variable} ${newsreader.variable} h-full antialiased`}
    >
      <body className="min-h-full bg-background text-foreground">
        <SessionKeyProvider>{children}</SessionKeyProvider>
      </body>
    </html>
  );
}
