import type { MetadataRoute } from "next";

export default function sitemap(): MetadataRoute.Sitemap {
  return [
    {
      url: "http://127.0.0.1:3000/",
      lastModified: new Date("2026-07-17"),
      changeFrequency: "monthly",
      priority: 1,
    },
  ];
}
