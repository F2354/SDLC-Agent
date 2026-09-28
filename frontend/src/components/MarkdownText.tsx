/**
 * 轻量 Markdown 渲染器。
 *
 * Agent 的对话输出、评审意见、阶段产物都是 Markdown（标题、列表、代码块、
 * 加粗、行内代码），此前一律以纯文本直出 —— 结构信息全部丢失。
 * 这里用最小实现渲染常用语法，不引入第三方依赖：
 * 代码块 / 标题 / 有序无序列表 / 引用 / 分割线 / 段落，
 * 行内支持 **加粗**、*斜体*、`行内代码`、[链接](url)。
 */
import { useState, type ReactNode } from 'react'

type Block =
  | { kind: 'code'; lang: string; code: string }
  | { kind: 'heading'; level: number; text: string }
  | { kind: 'ul'; items: string[] }
  | { kind: 'ol'; items: string[] }
  | { kind: 'quote'; text: string }
  | { kind: 'hr' }
  | { kind: 'p'; text: string }

const FENCE = /^\s*```\s*([\w+-]*)\s*$/
const HEADING = /^(#{1,6})\s+(.*)$/
const UL = /^\s*[-*+]\s+(.*)$/
const OL = /^\s*\d+[.)]\s+(.*)$/
const HR = /^\s*(-{3,}|_{3,}|\*{3,})\s*$/
const QUOTE = /^\s*>\s?(.*)$/

function parseBlocks(md: string): Block[] {
  const lines = (md ?? '').replace(/\r\n?/g, '\n').split('\n')
  const blocks: Block[] = []
  let i = 0
  let buffer: string[] = []

  const flushParagraph = () => {
    if (!buffer.length) return
    blocks.push({ kind: 'p', text: buffer.join('\n').trim() })
    buffer = []
  }

  while (i < lines.length) {
    const line = lines[i]
    const fence = line.match(FENCE)
    if (fence) {
      flushParagraph()
      const lang = fence[1] ?? ''
      const body: string[] = []
      i += 1
      while (i < lines.length && !FENCE.test(lines[i])) {
        body.push(lines[i])
        i += 1
      }
      i += 1 // 跳过结束围栏
      blocks.push({ kind: 'code', lang, code: body.join('\n') })
      continue
    }
    if (HR.test(line)) {
      flushParagraph()
      blocks.push({ kind: 'hr' })
      i += 1
      continue
    }
    const heading = line.match(HEADING)
    if (heading) {
      flushParagraph()
      blocks.push({ kind: 'heading', level: heading[1].length, text: heading[2].trim() })
      i += 1
      continue
    }
    const quote = line.match(QUOTE)
    if (quote) {
      flushParagraph()
      const parts: string[] = [quote[1]]
      i += 1
      while (i < lines.length && QUOTE.test(lines[i])) {
        parts.push(lines[i].match(QUOTE)![1])
        i += 1
      }
      blocks.push({ kind: 'quote', text: parts.join('\n') })
      continue
    }
    if (UL.test(line)) {
      flushParagraph()
      const items: string[] = []
      while (i < lines.length && UL.test(lines[i])) {
        items.push(lines[i].match(UL)![1])
        i += 1
      }
      blocks.push({ kind: 'ul', items })
      continue
    }
    if (OL.test(line)) {
      flushParagraph()
      const items: string[] = []
      while (i < lines.length && OL.test(lines[i])) {
        items.push(lines[i].match(OL)![1])
        i += 1
      }
      blocks.push({ kind: 'ol', items })
      continue
    }
    if (!line.trim()) {
      flushParagraph()
      i += 1
      continue
    }
    buffer.push(line)
    i += 1
  }
  flushParagraph()
  return blocks
}

/** 行内语法：**加粗** / *斜体* / `代码` / [文本](链接) */
function renderInline(text: string, keyPrefix: string): ReactNode[] {
  const pattern = /(\*\*[^*]+\*\*)|(`[^`]+`)|(\[[^\]]+\]\([^)]+\))|(\*[^*\n]+\*)/g
  const nodes: ReactNode[] = []
  let last = 0
  let match: RegExpExecArray | null
  let index = 0

  while ((match = pattern.exec(text)) !== null) {
    if (match.index > last) nodes.push(text.slice(last, match.index))
    const token = match[0]
    const key = `${keyPrefix}-i${index++}`
    if (token.startsWith('**')) {
      nodes.push(<strong key={key} className="md-strong">{token.slice(2, -2)}</strong>)
    } else if (token.startsWith('`')) {
      nodes.push(<code key={key} className="md-inline-code">{token.slice(1, -1)}</code>)
    } else if (token.startsWith('[')) {
      const link = token.match(/\[([^\]]+)\]\(([^)]+)\)/)!
      nodes.push(
        <a key={key} className="md-link" href={link[2]} target="_blank" rel="noreferrer">
          {link[1]}
        </a>,
      )
    } else {
      nodes.push(<em key={key}>{token.slice(1, -1)}</em>)
    }
    last = match.index + token.length
  }
  if (last < text.length) nodes.push(text.slice(last))
  return nodes.length ? nodes : [text]
}

function CodeBlock({ lang, code }: { lang: string; code: string }) {
  const [copied, setCopied] = useState(false)
  const copy = () => {
    void navigator.clipboard?.writeText(code).then(
      () => {
        setCopied(true)
        window.setTimeout(() => setCopied(false), 1600)
      },
      () => setCopied(false),
    )
  }
  return (
    <div className="md-code-block">
      <div className="md-code-head">
        <span>{lang || 'text'}</span>
        <button type="button" onClick={copy}>{copied ? '已复制' : '复制'}</button>
      </div>
      <pre>{code}</pre>
    </div>
  )
}

export function MarkdownText({ text, className = '' }: { text: string; className?: string }) {
  const blocks = parseBlocks(text)
  return (
    <div className={`md-body ${className}`.trim()}>
      {blocks.map((block, index) => {
        const key = `b${index}`
        switch (block.kind) {
          case 'code':
            return <CodeBlock key={key} lang={block.lang} code={block.code} />
          case 'heading':
            return block.level <= 2
              ? <h3 key={key} className="md-h">{renderInline(block.text, key)}</h3>
              : <h4 key={key} className="md-h md-h-sub">{renderInline(block.text, key)}</h4>
          case 'ul':
            return (
              <ul key={key} className="md-list">
                {block.items.map((item, i) => <li key={`${key}-${i}`}>{renderInline(item, `${key}-${i}`)}</li>)}
              </ul>
            )
          case 'ol':
            return (
              <ol key={key} className="md-list md-list-ordered">
                {block.items.map((item, i) => <li key={`${key}-${i}`}>{renderInline(item, `${key}-${i}`)}</li>)}
              </ol>
            )
          case 'quote':
            return <blockquote key={key} className="md-quote">{renderInline(block.text, key)}</blockquote>
          case 'hr':
            return <hr key={key} className="md-hr" />
          default:
            return <p key={key} className="md-p">{renderInline(block.text, key)}</p>
        }
      })}
    </div>
  )
}
