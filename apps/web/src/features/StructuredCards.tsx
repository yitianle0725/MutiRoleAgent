// 结构化输出卡片：根据 schema_type 渲染不同卡片，禁止原始 JSON 文本直接展示
// StructuredData 与最终自然语言分离，只携带 schema_type 和结构化 data。
import type { CSSProperties } from 'react'

export interface StructuredPayload {
  schema_type: string
  data: Record<string, unknown>
}

/** 通用封面占位（无图时显示首字 + 渐变背景） */
function CoverThumb({ name, src }: { name: string; src?: string | null }) {
  const initial = name?.charAt(0) || '?'
  if (src) {
    return <img className="anime-card-cover-img" src={src} alt={name} loading="lazy" />
  }
  return (
    <div className="anime-card-cover-fallback">
      <span>{initial}</span>
    </div>
  )
}

/** 单张番剧卡片 */
function AnimeCard({ item, index }: { item: Record<string, unknown>; index: number }) {
  const title = (item.chinese_name as string) || (item.japanese_name as string) || '未知作品'
  const jp = (item.japanese_name as string) || ''
  const score = item.score as number | null | undefined
  const rank = item.rank as number | null | undefined
  const tags = (item.tags as string[]) || []
  const reason = (item.reason as string) || ''
  const url = (item.url as string) || ''
  const cover = (item.cover as string | null | undefined) ?? null
  return (
    <div className="anime-card">
      <CoverThumb name={title} src={cover} />
      <div className="anime-card-body">
        <div className="anime-card-index">#{index + 1}</div>
        <h3 className="anime-card-title">{title}</h3>
        {jp && <div className="anime-card-jp">{jp}</div>}
        <div className="anime-card-meta">
          {score != null && <span className="anime-card-score">⭐ {score}</span>}
          {rank != null && <span className="anime-card-rank">🏆 #{rank}</span>}
        </div>
        {tags.length > 0 && (
          <div className="anime-card-tags">
            {tags.map((t) => (
              <span key={t} className="anime-card-tag">{t}</span>
            ))}
          </div>
        )}
        {reason && <p className="anime-card-reason">{reason}</p>}
        {url && (
          <a className="anime-card-link" href={url} target="_blank" rel="noreferrer">
            查看详情 →
          </a>
        )}
      </div>
    </div>
  )
}

/** 番剧推荐列表 */
function AnimeRecommendationView({ data }: { data: Record<string, unknown> }) {
  const items = (data.items as Record<string, unknown>[]) || []
  return (
    <div className="structured-card-list">
      {items.map((it, i) => (
        <AnimeCard key={i} item={it} index={i} />
      ))}
    </div>
  )
}

/** 季度新番概览 */
function SeasonOverviewView({ data }: { data: Record<string, unknown> }) {
  const seasonLabel = (data.season_label as string) || ''
  const totalCount = (data.total_count as number) || 0
  const items = (data.top_items as Record<string, unknown>[]) || []
  return (
    <div className="structured-season">
      <div className="structured-season-header">
        <span className="structured-season-label">{seasonLabel}</span>
        <span className="structured-season-total">共 {totalCount} 部</span>
      </div>
      <div className="structured-card-list">
        {items.map((it, i) => (
          <AnimeCard key={i} item={it} index={i} />
        ))}
      </div>
    </div>
  )
}

/** 番剧深度解析 */
function AnimeDeepDiveView({ data }: { data: Record<string, unknown> }) {
  const title = (data.title as string) || (data.chinese_name as string) || '未知作品'
  const score = data.score as number | null | undefined
  const synopsis = (data.synopsis as string) || ''
  const cast = (data.cast as Array<{ character: string; voice_actor: string }>) || []
  return (
    <div className="structured-deepdive">
      <CoverThumb name={title} src={data.cover as string | null | undefined} />
      <div className="structured-deepdive-body">
        <h3 className="anime-card-title">{title}</h3>
        {score != null && <span className="anime-card-score">⭐ {score}</span>}
        {synopsis && <p className="structured-synopsis">{synopsis}</p>}
        {cast.length > 0 && (
          <div className="structured-cast">
            <div className="structured-cast-title">配音阵容</div>
            {cast.map((c, i) => (
              <div key={i} className="structured-cast-row">
                <span className="structured-cast-char">{c.character}</span>
                <span className="structured-cast-va">{c.voice_actor}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

/** 天气报告 */
function WeatherReportView({ data }: { data: Record<string, unknown> }) {
  const city = (data.city as string) || ''
  const temp = data.temperature as number | null | undefined
  const humidity = data.humidity as number | null | undefined
  const condition = (data.condition as string) || ''
  const feelsLike = data.feels_like as number | null | undefined
  const advice = (data.advice as string) || ''
  return (
    <div className="structured-weather">
      <div className="structured-weather-city">{city}</div>
      <div className="structured-weather-main">
        {temp != null && <div className="structured-weather-temp">{temp}°C</div>}
        <div className="structured-weather-cond">{condition}</div>
      </div>
      <div className="structured-weather-detail">
        {feelsLike != null && <span>体感 {feelsLike}°C</span>}
        {humidity != null && <span>湿度 {humidity}%</span>}
      </div>
      {advice && <div className="structured-weather-advice">{advice}</div>}
    </div>
  )
}

/** 未注册卡片只显示类型，不把原始 JSON 暴露到聊天正文。 */
function FallbackView({ schemaType }: { schemaType: string }) {
  return <div className="structured-fallback">暂不支持此卡片：{schemaType}</div>
}

export function StructuredCards({ data }: { data: StructuredPayload }) {
  const wrapStyle: CSSProperties = { margin: '12px 0' }
  switch (data.schema_type) {
    case 'anime_recommendation':
      return <div style={wrapStyle}><AnimeRecommendationView data={data.data} /></div>
    case 'season_overview':
      return <div style={wrapStyle}><SeasonOverviewView data={data.data} /></div>
    case 'anime_deep_dive':
      return <div style={wrapStyle}><AnimeDeepDiveView data={data.data} /></div>
    case 'weather_report':
      return <div style={wrapStyle}><WeatherReportView data={data.data} /></div>
    default:
      return <div style={wrapStyle}><FallbackView schemaType={data.schema_type} /></div>
  }
}
