(function () {
  "use strict";

  const DEFAULT_NOTE_MODE = "none";
  const ADJUST_NOTE_RE = /\s*[（(](上调|下调|↑|↓)\s*(\d{1,5})\s*(?:元)?[)）]\s*/g;

  function autoFormatContent(content) {
    const lines = String(content || "").trim().split("\n");
    const out = [];
    lines.forEach((rawLine) => {
      const line = String(rawLine || "").trim();
      if (!line) {
        out.push("");
        return;
      }
      if (line.startsWith("【") || line.includes("：") || line.includes(":")) {
        out.push(line);
        return;
      }
      const match = line.match(/^([^\d\s]+)\s*(\d{3,5})(?:\s*元)?$/);
      if (match) {
        out.push(`【${match[1]}】：${match[2]} 元/吨`);
      } else {
        out.push(line);
      }
    });
    return out.join("\n").trim();
  }

  function validateContent(content) {
    const warnings = [];
    const text = String(content || "");
    const matches = text.matchAll(/(\d{1,5})(?:\s*元)?/g);
    for (const match of matches) {
      const price = Number(match[1]);
      if (price === 0) {
        warnings.push("发现价格为 0 元");
      } else if (price > 9999) {
        warnings.push(`价格 ${price} 元可能过高`);
      }
    }
    return { valid: warnings.length === 0, warnings };
  }

  function normalizeBatchAdjustNoteMode(mode, legacyShowNote) {
    const text = String(mode || "").trim().toLowerCase();
    if (text === "none" || text === "text" || text === "arrow") return text;
    return legacyShowNote ? "text" : DEFAULT_NOTE_MODE;
  }

  function stripAdjustNote(text) {
    return String(text || "").replace(ADJUST_NOTE_RE, "");
  }

  function formatAdjustedNumber(rawValue, amount) {
    const value = Number(rawValue);
    if (!Number.isFinite(value)) return "";
    const adjusted = Math.max(0, value + amount);
    return Number.isInteger(adjusted) ? String(adjusted) : adjusted.toFixed(2).replace(/0+$/, "").replace(/\.$/, "");
  }

  function batchAdjustContent(content, amount, noteMode = DEFAULT_NOTE_MODE) {
    const delta = Number(amount || 0);
    const mode = normalizeBatchAdjustNoteMode(noteMode);
    const text = String(content || "");

    function replRange(match, leftRaw, rightRaw) {
      const left = Math.max(0, Number(leftRaw) + delta);
      const right = Math.max(0, Number(rightRaw) + delta);
      return `${left}-${right}`;
    }

    function protectRanges(value) {
      const holders = [];
      const protectedText = String(value || "").replace(/(\d{3,5})\s*[-~～至到]\s*(\d{3,5})/g, (match, left, right) => {
        const token = `__RANGE_TOKEN_${holders.length}__`;
        holders.push(replRange(match, left, right));
        return token;
      });
      return { protectedText, holders };
    }

    function restoreRanges(value, holders) {
      let out = String(value || "");
      holders.forEach((replacement, idx) => {
        out = out.replaceAll(`__RANGE_TOKEN_${idx}__`, replacement);
      });
      return out;
    }

    function formatNote() {
      if (mode === "arrow") return `（${delta >= 0 ? "↑" : "↓"}${Math.abs(delta)}）`;
      if (mode === "text") return `（${delta >= 0 ? "上调" : "下调"}${Math.abs(delta)}）`;
      return "";
    }

    function adjustStructuredLine(line) {
      const match = String(line || "").match(/^(\s*(?:【[^】]{1,30}】|[^：:\s][^：:\n]{0,30})\s*[：:]\s*)(.*?)(\s*)$/);
      if (!match) return null;
      const prefix = match[1];
      const body = stripAdjustNote(match[2]).trim();
      const suffix = match[3] || "";
      const bodyMatch = body.match(/^\s*(-?\d+(?:\.\d+)?(?:\s*[-~～至到]\s*-?\d+(?:\.\d+)?)?)\s*(元\s*\/\s*吨|\/\s*吨|[^\d\s（）()]+(?:\s*\/\s*[^\d\s（）()]+)*)?\s*$/);
      if (!bodyMatch) return null;
      let valueText = bodyMatch[1].trim();
      let unitText = String(bodyMatch[2] || "").replace(/\s+/g, "");
      const range = valueText.match(/^(-?\d+(?:\.\d+)?)\s*[-~～至到]\s*(-?\d+(?:\.\d+)?)$/);
      if (range) {
        const left = formatAdjustedNumber(range[1], delta);
        const right = formatAdjustedNumber(range[2], delta);
        if (!left || !right) return null;
        valueText = `${left}-${right}`;
      } else {
        const single = valueText.match(/^-?\d+(?:\.\d+)?$/);
        if (!single) return null;
        valueText = formatAdjustedNumber(valueText, delta);
      }
      if (unitText === "/吨") unitText = "元/吨";
      const note = formatNote();
      if (note && unitText === "元/吨") return `${prefix}${valueText}${note}元/吨${suffix}`;
      if (note && unitText) return `${prefix}${valueText}${note}${unitText.startsWith("/") ? "" : " "}${unitText}${suffix}`;
      if (note) return `${prefix}${valueText}${note}${suffix}`;
      return `${prefix}${valueText}${unitText ? ` ${unitText}` : ""}${suffix}`;
    }

    function adjustLine(line) {
      const raw = String(line || "");
      if (!raw.trim()) return raw;
      const structured = adjustStructuredLine(raw);
      if (structured !== null) return structured;

      const rawNoNote = stripAdjustNote(raw);
      const protectedRange = protectRanges(rawNoNote);
      let out = protectedRange.protectedText.replace(/(上调|下调)\s*(\d{1,5})/g, () => `${delta >= 0 ? "上调" : "下调"}${Math.abs(delta)}`);
      out = out.replace(/(?<!\d)(\d{3,5})(?!\d)/g, (match) => String(Math.max(0, Number(match) + delta)));
      return restoreRanges(out, protectedRange.holders);
    }

    return text.split("\n").map(adjustLine).join("\n").trim();
  }

  window.PosterTextTools = {
    autoFormatContent,
    validateContent,
    batchAdjustContent,
    normalizeBatchAdjustNoteMode,
  };
})();
