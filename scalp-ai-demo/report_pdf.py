"""Create a downloadable Korean report without storing photos or report files.

Displayed grades are recalculated from raw probabilities, just like app.js;
caller-supplied headings, labels, filenames and HTML are never trusted.
"""
from __future__ import annotations

import io
import math
import os
import threading
from datetime import date, datetime
from pathlib import Path
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

METRIC_IDS = ("flakes", "sebum", "hair_loss", "erythema")
NAMES = {"flakes": "각질", "sebum": "피지 유무", "hair_loss": "탈모 여부", "erythema": "모낭사이홍반"}
CURRENT_FLAKES = "flakes-384-square-v1"
CURRENT_SEBUM = "sebum-384-attention-v1"
FONT_NAME = "ScalpReportKorean"
FONT_BOLD = "ScalpReportKoreanBold"
FONT_LOCK = threading.Lock()


class ReportValidationError(ValueError):
    pass


class ReportFontError(RuntimeError):
    pass


def _metrics(values):
    if not isinstance(values, list) or len(values) != 4:
        raise ReportValidationError("보고서에 포함할 네 가지 분석 결과를 확인해 주세요.")
    displayed = []
    for index, model_id in enumerate(METRIC_IDS):
        metric = values[index]
        if not isinstance(metric, dict) or metric.get("id") != model_id:
            raise ReportValidationError("분석 항목의 순서와 내용을 확인해 주세요.")
        probabilities = metric.get("probabilities")
        expected = 4 if model_id == "flakes" else 3
        if (not isinstance(probabilities, list) or len(probabilities) != expected
                or any(isinstance(value, bool) or not isinstance(value, (int, float))
                       or not 0 <= value <= 1 or not math.isfinite(value) for value in probabilities)
                or abs(sum(probabilities) - 1) >= 0.01):
            raise ReportValidationError("분석 결과의 수치 형식을 확인해 주세요.")
        binary = model_id == "sebum" and metric.get("preprocessing_version") == CURRENT_SEBUM
        if model_id == "flakes":
            merged = [probabilities[0], probabilities[1] + probabilities[2], probabilities[3]]
            labels = ("정상", "경중등도", "중증")
        elif binary:
            merged = [probabilities[0], probabilities[1] + probabilities[2]]
            labels = ("무", "유")
        else:
            merged = probabilities
            labels = ("정상", "경증", "중증")
        grade = max(range(len(merged)), key=merged.__getitem__)
        displayed.append({
            "id": model_id, "name": "피지과다 (이전 기준)" if model_id == "sebum" and not binary else NAMES[model_id],
            "label": labels[grade], "grade": grade, "binary": binary,
            "legacy": (model_id == "sebum" and not binary) or (model_id == "flakes" and metric.get("preprocessing_version") != CURRENT_FLAKES),
        })
    return displayed


def report_data(result):
    """Bound and normalize an on-screen result, including older saved records."""
    if not isinstance(result, dict) or result.get("source") != "model":
        raise ReportValidationError("먼저 두피 사진을 분석한 뒤 보고서를 저장해 주세요.")
    analysis_date = result.get("date")
    try:
        if not isinstance(analysis_date, str) or date.fromisoformat(analysis_date).isoformat() != analysis_date:
            raise ValueError()
    except (ValueError, TypeError):
        raise ReportValidationError("분석 날짜를 확인해 주세요.") from None
    photo_count = result.get("photo_count")
    if type(photo_count) is not int or not 1 <= photo_count <= 3:
        raise ReportValidationError("분석 사진 수를 확인해 주세요.")
    if result.get("aggregation") != "mean_probabilities":
        raise ReportValidationError("사진 종합 방식을 확인해 주세요.")
    metrics = _metrics(result.get("metrics"))
    per_photo = result.get("per_photo")
    if not isinstance(per_photo, list) or len(per_photo) != photo_count:
        raise ReportValidationError("사진별 분석 결과를 확인해 주세요.")
    photos = []
    for index, photo in enumerate(per_photo):
        if not isinstance(photo, dict) or type(photo.get("index")) is not int or photo["index"] != index:
            raise ReportValidationError("사진별 분석 순서를 확인해 주세요.")
        photos.append(_metrics(photo.get("metrics")))
    return {"date": analysis_date, "photo_count": photo_count, "metrics": metrics, "photos": photos,
            "legacy": any(metric["legacy"] for metric in metrics)}


def _font_paths():
    configured = os.environ.get("SCALP_PDF_FONT")
    if configured:
        regular = Path(configured)
        bold = Path(os.environ.get("SCALP_PDF_BOLD_FONT") or configured)
        return regular, bold
    windows = Path(os.environ.get("SystemRoot", "C:/Windows")) / "Fonts"
    root = Path(__file__).resolve().parent
    candidates = [
        (windows / "malgun.ttf", windows / "malgunbd.ttf"),
        (root / "fonts" / "NotoSansKR-Regular.ttf", root / "fonts" / "NotoSansKR-Bold.ttf"),
        (Path("/usr/share/fonts/truetype/nanum/NanumGothic.ttf"), Path("/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf")),
    ]
    for regular, bold in candidates:
        if regular.is_file():
            return regular, bold if bold.is_file() else regular
    raise ReportFontError("PDF 저장에 필요한 한글 글꼴을 준비하지 못했어요. 운영자에게 문의해 주세요.")


def _register_fonts():
    with FONT_LOCK:
        if FONT_NAME in pdfmetrics.getRegisteredFontNames() and FONT_BOLD in pdfmetrics.getRegisteredFontNames():
            return
        regular, bold = _font_paths()
        if not regular.is_file() or not bold.is_file():
            raise ReportFontError("PDF 저장에 필요한 한글 글꼴을 찾지 못했어요. 운영자에게 문의해 주세요.")
        try:
            pdfmetrics.registerFont(TTFont(FONT_NAME, str(regular)))
            pdfmetrics.registerFont(TTFont(FONT_BOLD, str(bold)))
        except Exception as exc:
            raise ReportFontError("PDF 저장에 필요한 한글 글꼴을 읽지 못했어요. 운영자에게 문의해 주세요.") from exc
        pdfmetrics.registerFontFamily(FONT_NAME, normal=FONT_NAME, bold=FONT_BOLD, italic=FONT_NAME, boldItalic=FONT_BOLD)


def build_report_pdf(result: dict, profile: dict | None = None) -> bytes:
    data = report_data(result)
    _register_fonts()
    ink = colors.HexColor("#183d34")
    muted = colors.HexColor("#5b7068")
    accent = colors.HexColor("#176852")
    line = colors.HexColor("#d9e3de")
    styles = {
        "brand": ParagraphStyle("brand", fontName=FONT_BOLD, fontSize=12, leading=19, textColor=accent, wordWrap="CJK", spaceAfter=8),
        "title": ParagraphStyle("title", fontName=FONT_BOLD, fontSize=24, leading=32, textColor=ink, wordWrap="CJK", spaceAfter=13),
        "heading": ParagraphStyle("heading", fontName=FONT_BOLD, fontSize=12, leading=20, textColor=ink, wordWrap="CJK", spaceAfter=9),
        "body": ParagraphStyle("body", fontName=FONT_NAME, fontSize=10, leading=17, textColor=ink, wordWrap="CJK", spaceAfter=8),
        "small": ParagraphStyle("small", fontName=FONT_NAME, fontSize=8.5, leading=14, textColor=muted, wordWrap="CJK", spaceAfter=7),
        "label": ParagraphStyle("label", fontName=FONT_BOLD, fontSize=12, leading=19, textColor=accent, wordWrap="CJK"),
        "table": ParagraphStyle("table", fontName=FONT_NAME, fontSize=9, leading=15, textColor=ink, wordWrap="CJK"),
        "table_head": ParagraphStyle("table_head", fontName=FONT_BOLD, fontSize=9, leading=15, textColor=ink, wordWrap="CJK"),
    }
    def paragraph(text, style="body"):
        return Paragraph(escape(str(text)), styles[style])
    story = [paragraph("딥러닝 기반 AI 두피 관리 서비스", "brand"), paragraph("나의 두피 분석 보고서", "title")]
    nickname = profile.get("nickname") if isinstance(profile, dict) else None
    if isinstance(nickname, str) and 1 <= len(nickname) <= 40:
        story.append(paragraph(f"{nickname} 님의 분석 결과", "body"))
    story += [paragraph(f"분석일 {data['date']}  ·  사진 {data['photo_count']}장", "body"),
              paragraph("사진에서 확인한 네 가지 항목을 정리했어요. 등급은 사진에 나타난 특징을 분류한 결과예요.", "small"), Spacer(1, 4 * mm)]
    overview = [[paragraph("분석 항목", "table_head"), paragraph("분석 결과", "table_head")]]
    overview += [[paragraph(metric["name"]), paragraph(metric["label"], "label")] for metric in data["metrics"]]
    table = Table(overview, colWidths=[108 * mm, 64 * mm], hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eaf2ed")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7faf8")]),
        ("LINEBELOW", (0, 0), (-1, -1), 0.5, line),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 12), ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 9), ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
    ]))
    story += [table, Spacer(1, 4 * mm), paragraph("결과를 읽는 방법", "heading")]
    notes = ["각질의 경중등도는 경증과 중등도를 함께 나타내요."]
    if data["metrics"][1]["binary"]:
        notes.append("피지의 무·유는 관련 특징의 유무를 나타내며, 심한 정도를 뜻하지 않아요.")
    if data["photo_count"] > 1:
        notes.append("여러 사진은 각 사진의 분석값을 종합한 뒤 최종 등급을 정해요.")
    if data["legacy"]:
        notes.append("이전 분석 기준의 기록이 포함되어 있어요. 현재 기준으로 확인하려면 새 사진을 분석해 주세요.")
    notes.append("조명·초점·촬영 부위가 다르면 결과가 달라질 수 있어요. 결과만으로 호전이나 악화를 단정하지 마세요.")
    story += [paragraph(note, "small") for note in notes]
    if data["photo_count"] > 1:
        story += [Spacer(1, 3 * mm), paragraph("사진별 분석 결과", "heading")]
        photo_rows = [[paragraph("사진", "table_head")] + [paragraph(metric["name"], "table_head") for metric in data["metrics"]]]
        photo_rows += [[paragraph(f"사진 {index + 1}", "table")] + [paragraph(metric["label"], "table") for metric in metrics]
                       for index, metrics in enumerate(data["photos"])]
        photo_table = Table(photo_rows, colWidths=[20 * mm, 34 * mm, 37 * mm, 37 * mm, 44 * mm], repeatRows=1, hAlign="LEFT")
        photo_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eaf2ed")),
            ("LINEBELOW", (0, 0), (-1, -1), 0.5, line),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(photo_table)
    story += [Spacer(1, 4 * mm), KeepTogether([
              paragraph("두피를 관리할 때 기억해 주세요", "heading"),
              paragraph("두피에 맞는 세정 주기를 유지하고, 강하게 긁거나 문지르지 마세요. 다음 사진은 같은 부위·비슷한 조명에서 남겨 주세요.", "small"),
              paragraph("이 보고서는 의료 진단이나 치료 처방을 대신하지 않아요. 붉어짐·부기·심한 가려움이 계속되거나 탈모가 걱정되면 피부과에서 확인해 주세요.", "small")])]
    generated = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M")
    output = io.BytesIO()
    document = SimpleDocTemplate(output, pagesize=A4, rightMargin=19 * mm, leftMargin=19 * mm,
                                 topMargin=18 * mm, bottomMargin=20 * mm, title="나의 두피 분석 보고서",
                                 author="딥러닝 기반 AI 두피 관리 서비스", pageCompression=1)
    def footer(canvas, document):
        canvas.saveState()
        canvas.setStrokeColor(line)
        canvas.line(19 * mm, 15 * mm, A4[0] - 19 * mm, 15 * mm)
        canvas.setFont(FONT_NAME, 7.5)
        canvas.setFillColor(muted)
        canvas.drawString(19 * mm, 10 * mm, f"보고서 저장일 {generated} (한국 시간)")
        canvas.drawRightString(A4[0] - 19 * mm, 10 * mm, str(document.page))
        canvas.restoreState()
    document.build(story, onFirstPage=footer, onLaterPages=footer)
    return output.getvalue()
