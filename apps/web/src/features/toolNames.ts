// 工具中文名映射（对齐后端 agent/stream_events.py 的 TOOL_DISPLAY_NAMES）

const TOOL_DISPLAY_NAMES: Record<string, string> = {
  search_anime: '🔍 搜索动漫作品',
  fetch_anime: '📋 获取作品详情',
  get_season_anime: '📺 季度新番查询',
  rag_summarize: '📚 RAG 知识库检索',
  download_novel: '📚 小说下载（RAG）',
  maps_weather: '🌤️ 实时天气查询',
  maps_ip_location: '📍 IP 定位',
  get_public_ip: '🌐 获取公网 IP',
  switch_persona: '🎭 切换角色人设',
  reset_persona: '🔄 重置角色人设',
  web_search: '🌐 实时网络搜索',
  web_search_prime: '🌐 实时网络搜索（深度）',
  bailian_web_search: '🌐 实时网络搜索',
}

export function getToolDisplayName(toolName: string): string {
  if (!toolName) return '🔧 未知工具'
  if (TOOL_DISPLAY_NAMES[toolName]) return TOOL_DISPLAY_NAMES[toolName]
  if (toolName.toLowerCase().includes('search')) return `🔍 ${toolName}`
  if (toolName.includes('maps_')) return `📍 ${toolName.replace('maps_', '')}`
  return `🔧 ${toolName}`
}
