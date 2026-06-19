"""Minimal bilingual translation catalog for the Presentation layer.

Supports English (en) and Chinese Simplified (zh) without requiring
Babel or gettext at runtime. New strings go in both catalogs.
"""

from __future__ import annotations

from typing import Final

_EN: Final[dict[str, str]] = {
    # ── nav ──────────────────────────────────────────────────────────────
    "nav.library": "Library",
    "nav.upload": "Upload",
    "nav.health": "Health",
    # ── library ──────────────────────────────────────────────────────────
    "library.title": "Video Library",
    "library.empty": "No videos uploaded yet.",
    "library.upload_cta": "Upload a video to get started.",
    "library.video_count": "{n} video(s)",
    "library.storage": "Storage: {total}",
    # ── video card / status ───────────────────────────────────────────────
    "status.never_analyzed": "Not analyzed",
    "status.queued": "Queued",
    "status.running": "Running",
    "status.completed": "Completed",
    "status.failed": "Failed",
    "status.cancelled": "Cancelled",
    "status.idle": "Idle",
    # ── upload form ───────────────────────────────────────────────────────
    "upload.title": "Upload Video",
    "upload.label": "Select video file",
    "upload.hint": "Max 1 GB · Max 30 minutes · All common codecs accepted",
    "upload.submit": "Upload",
    "upload.uploading": "Uploading…",
    "upload.success": "Upload successful.",
    "upload.error": "Upload failed",
    # ── video detail ──────────────────────────────────────────────────────
    "detail.title": "Video Detail",
    "detail.filename": "Filename",
    "detail.duration": "Duration",
    "detail.resolution": "Resolution",
    "detail.fps": "Frame rate",
    "detail.codec": "Codec",
    "detail.status": "Status",
    "detail.analyze": "Start Analysis",
    "detail.reanalyze": "Reanalyze",
    "detail.delete": "Delete Video",
    "detail.artifacts": "Artifacts",
    "detail.runs": "Analysis Runs",
    "detail.no_runs": "No analysis runs yet.",
    # ── analysis progress ─────────────────────────────────────────────────
    "progress.title": "Analysis Progress",
    "progress.stage": "Stage",
    "progress.percent": "{pct}%",
    "progress.polling": "Refreshing…",
    "progress.done": "Analysis complete.",
    "progress.failed": "Analysis failed: {reason}",
    # ── backend form ──────────────────────────────────────────────────────
    "analysis.backend_name": "Backend",
    "analysis.backend_version": "Version",
    "analysis.start": "Start",
    # ── calibration ───────────────────────────────────────────────────────
    "calibration.title": "Calibration",
    "calibration.segment": "Segment",
    "calibration.rim": "Rim",
    "calibration.court": "Court Points",
    "calibration.save": "Save Calibration",
    "calibration.indicative": "Indicative only",
    # ── players ───────────────────────────────────────────────────────────
    "players.title": "Players",
    "players.no_players": "No players detected.",
    "players.rename": "Rename",
    "players.display_name": "Display name",
    "players.attempts": "Attempts",
    "players.makes": "Makes",
    # ── attempts review ───────────────────────────────────────────────────
    "attempts.title": "Attempts",
    "attempts.no_attempts": "No attempts found.",
    "attempts.outcome": "Outcome",
    "attempts.shot_type": "Shot type",
    "attempts.shooter": "Shooter",
    "attempts.location": "Location",
    "attempts.time": "Time",
    "attempts.confidence": "Confidence",
    "attempts.remove": "Remove",
    "attempts.restore": "Restore",
    "attempts.new": "Add Attempt",
    "attempts.prev": "Previous",
    "attempts.next": "Next",
    # ── outcomes ──────────────────────────────────────────────────────────
    "outcome.MADE": "Made",
    "outcome.MISSED": "Missed",
    "outcome.UNCERTAIN": "Uncertain",
    # ── statistics ────────────────────────────────────────────────────────
    "stats.title": "Statistics",
    "stats.attempts": "Attempts",
    "stats.makes": "Makes",
    "stats.misses": "Misses",
    "stats.pct": "Percentage",
    "stats.two_point": "2-Point",
    "stats.three_point": "3-Point",
    "stats.shot_chart": "Shot Chart",
    "stats.heatmap": "Heatmap",
    "stats.replay": "Replay",
    "stats.full_video": "Full Video",
    # ── tracking repair ───────────────────────────────────────────────────
    "tracking.title": "Tracking Repair",
    "tracking.instructions": "Click a point or draw a box to correct tracking.",
    "tracking.submit": "Submit Prompt",
    "tracking.kind_point": "Point",
    "tracking.kind_box": "Box",
    # ── deletion ──────────────────────────────────────────────────────────
    "deletion.title": "Delete Video",
    "deletion.warning": "This will permanently delete the video and all associated data.",
    "deletion.confirm_label": "Type the filename to confirm:",
    "deletion.confirm": "Delete Permanently",
    "deletion.cancel": "Cancel",
    # ── common ────────────────────────────────────────────────────────────
    "common.back": "Back",
    "common.save": "Save",
    "common.cancel": "Cancel",
    "common.loading": "Loading…",
    "common.error": "An error occurred.",
    "common.retry": "Retry",
    "common.low_confidence": "Low confidence",
    "common.seconds": "{n}s",
    "common.bytes": "{n} bytes",
    "common.unknown": "Unknown",
}

_ZH: Final[dict[str, str]] = {
    # ── nav ──────────────────────────────────────────────────────────────
    "nav.library": "视频库",
    "nav.upload": "上传",
    "nav.health": "系统状态",
    # ── library ──────────────────────────────────────────────────────────
    "library.title": "视频库",
    "library.empty": "尚未上传任何视频。",
    "library.upload_cta": "上传视频以开始使用。",
    "library.video_count": "{n} 个视频",
    "library.storage": "存储：{total}",
    # ── video card / status ───────────────────────────────────────────────
    "status.never_analyzed": "未分析",
    "status.queued": "已排队",
    "status.running": "分析中",
    "status.completed": "已完成",
    "status.failed": "失败",
    "status.cancelled": "已取消",
    "status.idle": "空闲",
    # ── upload form ───────────────────────────────────────────────────────
    "upload.title": "上传视频",
    "upload.label": "选择视频文件",
    "upload.hint": "最大 1 GB · 最长 30 分钟 · 支持所有常见编码格式",
    "upload.submit": "上传",
    "upload.uploading": "上传中…",
    "upload.success": "上传成功。",
    "upload.error": "上传失败",
    # ── video detail ──────────────────────────────────────────────────────
    "detail.title": "视频详情",
    "detail.filename": "文件名",
    "detail.duration": "时长",
    "detail.resolution": "分辨率",
    "detail.fps": "帧率",
    "detail.codec": "编解码器",
    "detail.status": "状态",
    "detail.analyze": "开始分析",
    "detail.reanalyze": "重新分析",
    "detail.delete": "删除视频",
    "detail.artifacts": "分析产物",
    "detail.runs": "分析记录",
    "detail.no_runs": "尚无分析记录。",
    # ── analysis progress ─────────────────────────────────────────────────
    "progress.title": "分析进度",
    "progress.stage": "阶段",
    "progress.percent": "{pct}%",
    "progress.polling": "刷新中…",
    "progress.done": "分析完成。",
    "progress.failed": "分析失败：{reason}",
    # ── backend form ──────────────────────────────────────────────────────
    "analysis.backend_name": "后端",
    "analysis.backend_version": "版本",
    "analysis.start": "开始",
    # ── calibration ───────────────────────────────────────────────────────
    "calibration.title": "校准",
    "calibration.segment": "片段",
    "calibration.rim": "篮圈",
    "calibration.court": "场地参考点",
    "calibration.save": "保存校准",
    "calibration.indicative": "仅供参考",
    # ── players ───────────────────────────────────────────────────────────
    "players.title": "球员",
    "players.no_players": "未检测到球员。",
    "players.rename": "重命名",
    "players.display_name": "显示名称",
    "players.attempts": "投篮次数",
    "players.makes": "命中",
    # ── attempts review ───────────────────────────────────────────────────
    "attempts.title": "投篮记录",
    "attempts.no_attempts": "未找到投篮记录。",
    "attempts.outcome": "结果",
    "attempts.shot_type": "投篮类型",
    "attempts.shooter": "投篮者",
    "attempts.location": "位置",
    "attempts.time": "时间",
    "attempts.confidence": "置信度",
    "attempts.remove": "移除",
    "attempts.restore": "恢复",
    "attempts.new": "添加投篮",
    "attempts.prev": "上一个",
    "attempts.next": "下一个",
    # ── outcomes ──────────────────────────────────────────────────────────
    "outcome.MADE": "命中",
    "outcome.MISSED": "未中",
    "outcome.UNCERTAIN": "不确定",
    # ── statistics ────────────────────────────────────────────────────────
    "stats.title": "统计数据",
    "stats.attempts": "投篮数",
    "stats.makes": "命中数",
    "stats.misses": "未中数",
    "stats.pct": "命中率",
    "stats.two_point": "两分球",
    "stats.three_point": "三分球",
    "stats.shot_chart": "投篮分布图",
    "stats.heatmap": "热力图",
    "stats.replay": "回放",
    "stats.full_video": "完整视频",
    # ── tracking repair ───────────────────────────────────────────────────
    "tracking.title": "轨迹修复",
    "tracking.instructions": "点击一个点或框选区域以修正轨迹。",
    "tracking.submit": "提交提示",
    "tracking.kind_point": "点",
    "tracking.kind_box": "框",
    # ── deletion ──────────────────────────────────────────────────────────
    "deletion.title": "删除视频",
    "deletion.warning": "此操作将永久删除视频及其所有相关数据。",
    "deletion.confirm_label": "输入文件名以确认：",
    "deletion.confirm": "永久删除",
    "deletion.cancel": "取消",
    # ── common ────────────────────────────────────────────────────────────
    "common.back": "返回",
    "common.save": "保存",
    "common.cancel": "取消",
    "common.loading": "加载中…",
    "common.error": "发生错误。",
    "common.retry": "重试",
    "common.low_confidence": "低置信度",
    "common.seconds": "{n} 秒",
    "common.bytes": "{n} 字节",
    "common.unknown": "未知",
}

_CATALOGS: Final[dict[str, dict[str, str]]] = {"en": _EN, "zh": _ZH}
SUPPORTED_LOCALES: Final[tuple[str, ...]] = ("en", "zh")
DEFAULT_LOCALE: Final[str] = "en"


def get_catalog(locale: str) -> dict[str, str]:
    """Return the translation catalog for the given locale, falling back to English."""
    return _CATALOGS.get(locale, _EN)


def t(key: str, locale: str = DEFAULT_LOCALE, **kwargs: str | int | float) -> str:
    """Translate key in locale, interpolating any keyword arguments."""
    catalog = get_catalog(locale)
    template = catalog.get(key) or _EN.get(key) or key
    if kwargs:
        return template.format(**kwargs)
    return template
