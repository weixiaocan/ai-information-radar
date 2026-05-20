import { defineCollection, z } from "astro:content";

const articleSchema = z.object({
  title: z.string(),
  date: z.string(),
  publishedDate: z.string(),
  type: z.enum(["daily", "weekly"]),
  routeSlug: z.string(),
  sourcePath: z.string(),
  published: z.boolean(),
});

const daily = defineCollection({
  type: "content",
  schema: articleSchema,
});

const weekly = defineCollection({
  type: "content",
  schema: articleSchema,
});

export const collections = { daily, weekly };
