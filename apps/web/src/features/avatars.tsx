// 头像占位模块 —— 之后补充真实头像图片时，只需替换这里的 import 或图片文件即可。
// 当前用同一张占位图（assets/hero.png），AI 与用户头像通过 CSS 类区分样式。
import placeholderImg from '../assets/hero.png'

/** Cyrene（AI 助手）头像占位。 */
export function AssistantAvatar() {
  return <img className="avatar-img avatar-assistant" src={placeholderImg} alt="Cyrene" />
}

/** 用户头像占位。 */
export function UserAvatar() {
  return <img className="avatar-img avatar-user" src={placeholderImg} alt="用户" />
}
