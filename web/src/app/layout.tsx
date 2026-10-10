import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "ResearchViz AI — Experiment Visualization Agent",
  description: "Turn machine learning experiment CSV files into publication-ready figures.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN" className="h-full antialiased">
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
