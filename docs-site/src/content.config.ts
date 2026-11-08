import { defineCollection } from 'astro:content'
import type { LoaderContext } from 'astro/loaders'
import { docsLoader } from '@astrojs/starlight/loaders'
import { docsSchema } from '@astrojs/starlight/schema'
import { build, SRC } from './manuals'

/** Starlight's own pages (src/content/docs: the start pages) plus the manuals, one page per chapter (see manuals.ts). */
const docs = docsLoader()

export const collections = {
  docs: defineCollection({
    schema: docsSchema(),
    loader: {
      name: 'kartei-docs',
      load: async (ctx) => {
        await docs.load(ctx) // first: it removes entries it didn't load itself
        await manuals(ctx)
        // `npm run dev`: an edited manual shows up without a restart
        ctx.watcher?.add(SRC)
        ctx.watcher?.on('change', (file) => { if (file.startsWith(SRC) && file.endsWith('.md')) manuals(ctx) })
      },
    },
  }),
}

let loaded = new Set<string>() // ids from the last run: a renamed chapter's old page goes away

async function manuals(ctx: LoaderContext) {
  const { pages, words } = build(ctx.config.base)
  for (const id of loaded) if (!pages.some((p) => p.id === id)) ctx.store.delete(id)
  loaded = new Set(pages.map((p) => p.id))
  for (const p of pages) {
    const data = await ctx.parseData({
      id: p.id,
      data: {
        title: p.title,
        sidebar: { order: p.order, ...(p.order === 0 ? { label: words[p.lang].overview } : {}) },
        editUrl: `https://github.com/undone37/Kartei/edit/main/${p.source}`,
      },
    })
    // a (virtual) path inside src/content/docs: Starlight builds the sidebar from it and takes the language of asides
    // and heading links from it; an overview page is its manual's index
    const filePath = `src/content/docs/${p.id}${p.order === 0 ? '/index' : ''}.md`
    const rendered = await ctx.renderMarkdown(p.body, { fileURL: new URL(filePath, ctx.config.root) })
    ctx.store.set({ id: p.id, data, body: p.body, filePath, rendered, digest: ctx.generateDigest(p.body) })
  }
}
