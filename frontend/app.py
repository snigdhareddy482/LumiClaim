"""Streamlit frontend for interacting with LumiClaim backend APIs."""

from __future__ import annotations

import base64
import html
import json
import os
import tempfile
from typing import Any

import requests
import streamlit as st
import streamlit.components.v1 as st_components


st.set_page_config(
	page_title="LumiClaim — Proof-first medical billing copilot",
	page_icon="🧮",
	layout="centered",
)

st.markdown(
	"""
		<style>
			:root {
				font-size: 17px;
			}
			body {
				letter-spacing: 0.01em;
			}
			.block-container {
				max-width: 960px !important;
				padding-top: 1.5rem !important;
				padding-bottom: 3rem !important;
			}
			[data-testid="stSpacer"] > div {
				height: 0.25rem !important;
			}
			@media (max-width: 768px) {
				.block-container {
					padding-left: 1.1rem !important;
					padding-right: 1.1rem !important;
				}
			}
			.section-spacer {
				margin-top: 1.5rem;
				margin-bottom: 1rem;
			}
		</style>
	""",
	unsafe_allow_html=True,
)
def _attach_session(kwargs: dict[str, Any]) -> dict[str, Any]:
	session_id = st.session_state.get("session_id")
	if not session_id:
		return kwargs
	params = dict(kwargs.get("params") or {})
	json_payload = kwargs.get("json")
	if isinstance(json_payload, dict):
		payload = dict(json_payload)
		payload.setdefault("session_id", session_id)
		kwargs["json"] = payload
	elif kwargs.get("files"):
		params.setdefault("session_id", session_id)
	else:
		params.setdefault("session_id", session_id)
	if params:
		kwargs["params"] = params
	return kwargs


def request_json(method: str, url: str, **kwargs: Any) -> tuple[dict[str, Any] | None, str | None]:
	kwargs = _attach_session(kwargs)
	try:
		response = requests.request(method, url, timeout=10, **kwargs)
		response.raise_for_status()
		return response.json(), None
	except requests.HTTPError as exc:
		try:
			payload = exc.response.json()
			message = json.dumps(payload, indent=2)
		except Exception:
			message = str(exc)
		return None, message
	except requests.RequestException as exc:
		return None, str(exc)


def format_currency(value: Any) -> str:
	try:
		numeric = float(value)
	except (TypeError, ValueError):
		return "—"
	return f"${numeric:,.2f}"


def humanize_formula(label: str, formula: str) -> str:
	if not formula:
		return label
	replacements = {"+": "+", "-": "−", "*": "×", "/": "÷"}
	spaced = (
		formula.replace("(", " ( ")
		.replace(")", " ) ")
		.replace("+", " + ")
		.replace("-", " - ")
		.replace("*", " * ")
		.replace("/", " / ")
	)
	tokens: list[str] = []
	for token in spaced.split():
		if token in replacements:
			tokens.append(replacements[token])
		elif token.isidentifier():
			tokens.append(token.replace("_", " ").title())
		else:
			tokens.append(token)
	return f"{label} = {' '.join(tokens)}"


def _slugify(value: str) -> str:
	filtered = [ch.lower() if ch.isalnum() else "-" for ch in value]
	slug = "".join(filtered).strip("-")
	return slug or "appeal"


def ensure_session(api_base: str) -> None:
	if not api_base:
		return
	if st.session_state.get("session_id"):
		return
	resp, err = request_json("POST", f"{api_base}/session/start")
	if err:
		st.sidebar.error(f"Unable to start session: {err}")
		return
	if isinstance(resp, dict) and resp.get("session_id"):
		sid = str(resp.get("session_id"))
		st.session_state["session_id"] = sid
		st.session_state.setdefault("profile_session_id", sid)
		st.session_state.setdefault("profile_session_id_input", sid)
		st.session_state.setdefault("dashboard_session_id", sid)


def render_copy_button(label: str, payload: str, key: str) -> None:
	encoded = base64.b64encode(payload.encode("utf-8")).decode("ascii")
	st_components.html(
		f"""
			<div style='display:inline-block;margin-right:8px;'>
				<button id="{key}" style="padding:6px 12px;border-radius:6px;border:1px solid #d1d5db;background-color:#f8fafc;color:#0f172a;font-size:0.85rem;cursor:pointer;">{label}</button>
			</div>
			<script>
				const btn = document.getElementById("{key}");
				if (btn) {{
					btn.addEventListener("click", () => {{
						navigator.clipboard.writeText(atob("{encoded}"));
						const original = btn.innerText;
						btn.innerText = original + " ✓";
						setTimeout(() => btn.innerText = original, 1500);
					}});
				}}
			</script>
		""",
		height=45,
	)


_PRIVACY_BADGE_HTML = (
	"<div style='display:flex;justify-content:flex-end;margin-top:18px;'>"
	"<span style='display:inline-block;padding:4px 12px;border-radius:999px;"
	"background-color:#0f766e;color:#ecfdf5;font-weight:600;'>"
	"Privacy: Redacted</span></div>"
)


def render_evidence_graph(graph_data: dict[str, Any]) -> None:
	nodes = graph_data.get("nodes") or []
	edges = graph_data.get("edges") or []
	max_rows = 10
	try:
		from pyvis.network import Network  # type: ignore
	except ModuleNotFoundError:
		Network = None

	if Network and nodes and edges:
		net = Network(height="300px", width="100%", notebook=False, directed=True)
		net.toggle_physics(False)
		color_map = {
			"amount": "#3b82f6",
			"code": "#f97316",
			"source": "#22c55e",
			"policy": "#8b5cf6",
			"warning": "#ef4444",
		}
		for node in nodes:
			node_id = node.get("id")
			if not node_id:
				continue
			label = node.get("label") or node_id
			color = color_map.get(node.get("kind"), "#6b7280")
			net.add_node(node_id, label=label, color=color)
		for edge in edges:
			source = edge.get("source")
			target = edge.get("target")
			if not (source and target):
				continue
			net.add_edge(source, target, label=edge.get("type", ""))
		try:
			html_str = net.generate_html(notebook=False)
		except TypeError:
			tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".html")
			tmp_path = tmp_file.name
			tmp_file.close()
			net.write_html(tmp_path)
			with open(tmp_path, "r", encoding="utf-8") as handle:
				html_str = handle.read()
			try:
				os.unlink(tmp_path)
			except OSError:
				pass

		st_components.html(html_str, height=320, scrolling=False)
		if len(nodes) + len(edges) > 20:
			st.caption("Preview trims to keep things readable. Check debug tools for full graph.")
		return

	node_limit = min(len(nodes), max_rows // 2 if edges else max_rows)
	remaining = max_rows - node_limit
	edge_limit = min(len(edges), remaining)
	node_rows = nodes[:node_limit]
	edge_rows = edges[:edge_limit]
	if node_rows:
		table_html = [
			"<table style='width:100%;border-collapse:collapse;margin-top:0.5rem;'>",
			"<thead><tr><th style='text-align:left;padding:6px;color:#0f172a;'>Node</th><th style='text-align:left;padding:6px;color:#0f172a;'>Type</th></tr></thead>",
			"<tbody>",
		]
		for node in node_rows:
			label = html.escape(str(node.get("label") or node.get("id", "")))
			kind = html.escape(str(node.get("kind", "")))
			table_html.append(
				f"<tr><td style='padding:6px;color:#1f2937;'>{label}</td><td style='padding:6px;color:#475569;'>{kind}</td></tr>"
			)
		table_html.append("</tbody></table>")
		st.markdown("".join(table_html), unsafe_allow_html=True)
	if edge_rows:
		edge_table = [
			"<table style='width:100%;border-collapse:collapse;margin-top:0.75rem;'>",
			"<thead><tr><th style='text-align:left;padding:6px;color:#0f172a;'>Relation</th><th style='text-align:left;padding:6px;color:#0f172a;'>Type</th></tr></thead>",
			"<tbody>",
		]
		for edge in edge_rows:
			source = html.escape(str(edge.get("source", "")))
			target = html.escape(str(edge.get("target", "")))
			rel = html.escape(str(edge.get("type", "")))
			edge_table.append(
				f"<tr><td style='padding:6px;color:#1f2937;'>{source} → {target}</td><td style='padding:6px;color:#475569;'>{rel}</td></tr>"
			)
		edge_table.append("</tbody></table>")
		st.markdown("".join(edge_table), unsafe_allow_html=True)
	if not node_rows and not edge_rows:
		st.caption("No graph data available.")
	elif len(nodes) > node_limit or len(edges) > edge_limit:
		st.caption("Preview limited to keep rows under ten.")

st.sidebar.caption("Try EOB-001 and EOB-002")

api_base = st.sidebar.text_input("API base URL", value="http://localhost:8080")
st.sidebar.caption("Try EOB-001 and EOB-002")

ensure_session(api_base.strip())
current_session_id = st.session_state.get("session_id")
if current_session_id:
	st.sidebar.markdown(f"**Session ID:** `{current_session_id}`")
	st.session_state.setdefault("dashboard_session_id", current_session_id)
	st.session_state.setdefault("profile_session_id", current_session_id)
	st.session_state.setdefault("profile_session_id_input", current_session_id)

if "current_doc_id" not in st.session_state:
	st.session_state["current_doc_id"] = "EOB-001"

doc_id_sidebar = st.sidebar.text_input(
	"Document ID",
	value=st.session_state["current_doc_id"],
	key="sidebar_doc_id",
)
if doc_id_sidebar and doc_id_sidebar.strip():
	st.session_state["current_doc_id"] = doc_id_sidebar.strip()

_STATE_DEFAULTS: dict[str, Any] = {
	"explain_data": None,
	"explain_error": None,
	"simulate_data": None,
	"simulate_error": None,
	"compare_data": None,
	"compare_error": None,
	"appeal_data": None,
	"appeal_error": None,
	"appeal_payload": None,
	"active_doc_id": None,
}
for _state_key, _default in _STATE_DEFAULTS.items():
	st.session_state.setdefault(_state_key, _default)

st.session_state.setdefault("tour_done", True)
st.session_state.setdefault("tour_step", 0)
st.session_state.setdefault("last_upload", None)
st.session_state.setdefault("privacy_redacted_doc", None)
st.session_state.setdefault("redacted_preview", None)
st.session_state.setdefault("favorite_doc_id", None)

# Sidebar: Audit & Privacy — show last explain/appeal audit hashes and allow purge

with st.sidebar.expander("Audit & Privacy", expanded=False):
	st.markdown("Show audit hashes for the most recent Explain and Appeal operations for this session.")
	refresh_clicked = st.button("Refresh audit hashes", key="audit_refresh_button")
	audit_cache = st.session_state.get("_audit_latest_cache")
	if refresh_clicked or not audit_cache or audit_cache.get("session_id") != current_session_id:
		if current_session_id:
			with st.spinner("Fetching audit status..."):
				resp, err = request_json("GET", f"{api_base}/audit/latest")
			st.session_state["_audit_latest_cache"] = {
				"data": resp,
				"error": err,
				"session_id": current_session_id,
			}
		audit_cache = st.session_state.get("_audit_latest_cache")

	audit_error = audit_cache.get("error") if audit_cache else None
	audit_data = audit_cache.get("data") if audit_cache else None

	if audit_error:
		st.error(f"Audit lookup failed: {audit_error}")
	elif isinstance(audit_data, dict):
		latest_explain = audit_data.get("latest_explain") or {}
		latest_appeal = audit_data.get("latest_appeal") or {}
		if latest_explain:
			st.write("Latest Explain audit:", f"`{latest_explain.get('audit_hash', '—')}`", f"({latest_explain.get('timestamp', 'unknown')})")
		else:
			st.write("Latest Explain audit:", "(none yet)")
		if latest_appeal:
			st.write("Latest Appeal audit:", f"`{latest_appeal.get('audit_hash', '—')}`", f"({latest_appeal.get('timestamp', 'unknown')})")
		else:
			st.write("Latest Appeal audit:", "(none yet)")
	else:
		st.write("Latest Explain audit:", "(unknown)")
		st.write("Latest Appeal audit:", "(unknown)")

	st.markdown("---")
	st.markdown("<small>Purge will delete files under <code>data/user_sessions/&lt;session_id&gt;</code> on the server.</small>", unsafe_allow_html=True)
	if st.session_state.pop("_purge_reset_flag", False):
		st.session_state["confirm_purge_checkbox"] = False
	confirm_purge = st.checkbox(
		"I understand this permanently deletes my uploaded and extracted data.",
		key="confirm_purge_checkbox",
	)
	display_session_value = str(current_session_id) if current_session_id else ""
	st.text_input(
		"Session ID",
		value=display_session_value,
		disabled=True,
		key="purge_session_display",
	)
	if st.button("Purge session data", key="purge_session_button"):
		if not confirm_purge:
			st.error("Please confirm the purge by checking the box before proceeding.")
		else:
			sid = (current_session_id or "").strip()
			if not sid:
				st.error("No active session to purge.")
			else:
				base_url = api_base.strip()
				if not base_url:
					st.error("Provide an API base URL before purging.")
				else:
					with st.spinner("Purging session data..."):
						purge_kwargs = _attach_session({"json": {"session_id": sid}})
						try:
							response = requests.post(
								f"{base_url}/session/purge",
								timeout=10,
								**purge_kwargs,
							)
						except requests.RequestException as exc:
							st.error(f"Purge failed: {exc}")
						else:
							status_code = response.status_code
							if status_code == 404:
								try:
									error_payload = response.json()
								except ValueError:
									error_payload = {"detail": response.text or "session not found"}
								detail = error_payload.get("detail") or "session not found"
								st.error(f"Purge failed: {detail}")
								available_sessions = error_payload.get("available_sessions")
								if available_sessions:
									session_rows: list[dict[str, str]] = []
									metadata: dict[str, dict[str, Any]] = {}
									try:
										list_response = requests.get(f"{base_url}/session/list", timeout=10)
										if list_response.ok:
											payload = list_response.json()
											if isinstance(payload, dict):
												for item in payload.get("sessions", []) or []:
													if isinstance(item, dict) and item.get("session_id"):
														metadata[str(item["session_id"])] = item
									except requests.RequestException:
										metadata = {}
									for sid in available_sessions:
										sid_str = str(sid)
										info = metadata.get(sid_str, {})
										created_at = str(info.get("created_at")) if info.get("created_at") else "—"
										doc_count = info.get("doc_count")
										doc_display = str(doc_count) if doc_count is not None else "—"
										session_rows.append({"id": sid_str, "created_at": created_at, "docs": doc_display})
									if session_rows:
										table_html = [
											"<table style='width:100%;border-collapse:collapse;margin-top:8px;'>",
											"<thead><tr>",
											"<th style='text-align:left;padding:6px;border-bottom:1px solid #e2e8f0;'>Session ID</th>",
											"<th style='text-align:left;padding:6px;border-bottom:1px solid #e2e8f0;'>Created</th>",
											"<th style='text-align:right;padding:6px;border-bottom:1px solid #e2e8f0;'>Docs</th>",
											"</tr></thead><tbody>",
										]
										for row in session_rows:
											row_html = (
												f"<tr><td style='padding:6px;border-bottom:1px solid #f1f5f9;color:#0f172a;'>{html.escape(row['id'])}</td>"
												f"<td style='padding:6px;border-bottom:1px solid #f1f5f9;color:#475569;'>{html.escape(row['created_at'])}</td>"
												f"<td style='padding:6px;border-bottom:1px solid #f1f5f9;color:#0f172a;text-align:right;'>{html.escape(row['docs'])}</td></tr>"
											)
											table_html.append(row_html)
										table_html.append("</tbody></table>")
										st.markdown("".join(table_html), unsafe_allow_html=True)
										selected_session = st.radio(
											"Switch to an existing session",
											[row["id"] for row in session_rows],
											index=0,
											key="purge_session_switch_choice",
										)
										if st.button("Switch to this session", key="purge_session_switch_button"):
											chosen = selected_session
											st.session_state["session_id"] = chosen
											st.session_state.setdefault("dashboard_session_id", chosen)
											st.session_state.setdefault("profile_session_id", chosen)
											st.session_state.setdefault("profile_session_id_input", chosen)
											st.success(f"Switched to session {chosen}.")
							elif status_code >= 400:
								try:
									error_payload = response.json()
								except ValueError:
									error_payload = {"detail": response.text or f"HTTP {status_code}"}
								detail = error_payload.get("detail") or f"HTTP {status_code}"
								st.error(f"Purge failed: {detail}")
							else:
								try:
									resp_data = response.json()
								except ValueError:
									resp_data = {}
								# clear local session keys that may reference the purged session
								for k in [
									"last_upload",
									"profile_data",
									"profile_session_id",
									"profile_session_id_input",
									"dashboard_session_id",
									"redacted_preview",
									"privacy_redacted_doc",
									"explain_data",
									"appeal_data",
									"favorite_doc_id",
									"purge_session_id",
								]:
									if k in st.session_state:
										try:
											del st.session_state[k]
										except Exception:
											pass
								st.session_state["_purge_reset_flag"] = True
								if "session_id" in st.session_state:
									try:
										del st.session_state["session_id"]
									except Exception:
										pass
								# show audit hash if returned
								if isinstance(resp_data, dict) and resp_data.get("audit_hash"):
									st.caption(f"Server audit: `{resp_data.get('audit_hash')}`")
								ensure_session(base_url)
								st.success("Session purged and restarted.")

TOUR_STEPS: list[dict[str, str]] = [
	{
		"title": "Review tab",
		"body": (
			"Run Explain to break down a claim, inspect risk flags, and grab citations. "
			"Use the controls here to change persona and reading level."
		),
	},
	{
		"title": "Simulate payments",
		"body": (
			"Adjust deductible, coinsurance, and out-of-pocket values to preview what the member "
			"should owe versus the bill."
		),
	},
	{
		"title": "Compare & appeal",
		"body": (
			"Hop over to the Actions tab to diff two EOBs, assemble a proof pack, and download "
			"ready-to-send appeals in DOCX or PDF."
		),
	},
]


def _render_tour_overlay() -> None:
	if st.session_state.get("tour_done", False):
		return
	step_index = st.session_state.get("tour_step", 0)
	step_index = max(0, min(step_index, len(TOUR_STEPS) - 1))
	step = TOUR_STEPS[step_index]
	tour_container = st.empty()
	with tour_container.container():
		st.markdown(
			f"""
				<style>
					.tour-backdrop {{
						position: fixed;
						inset: 0;
						background: rgba(15, 23, 42, 0.55);
						backdrop-filter: blur(2px);
						z-index: 1000;
					}}
					.tour-card {{
						position: fixed;
						top: 18%;
						left: 50%;
						transform: translateX(-50%);
						background: #ffffff;
						padding: 24px 26px;
						border-radius: 14px;
						box-shadow: 0 18px 42px rgba(15, 23, 42, 0.25);
						width: min(420px, 92vw);
						z-index: 1001;
						color: #0f172a;
					}}
					.tour-card h3 {{
						margin-bottom: 0.6rem;
					}}
					.tour-card p {{
						margin-bottom: 0;
						font-size: 0.95rem;
						line-height: 1.5;
					}}
					.tour-progress {{
						font-size: 0.8rem;
						letter-spacing: 0.08em;
						text-transform: uppercase;
						color: #6366f1;
						font-weight: 700;
						margin-bottom: 0.5rem;
						display: inline-block;
					}}
					.tour-controls {{
						position: fixed;
						top: calc(18% + 240px);
						left: 50%;
						transform: translateX(-50%);
						width: min(420px, 92vw);
						z-index: 1001;
					}}
					.tour-controls > div {{
						display: flex;
						gap: 10px;
					}}
					.tour-controls button {{
						width: 100%;
						border-radius: 999px;
					}}
					@media (max-width: 600px) {{
						.tour-card {{
							top: 14%;
						}}
						.tour-controls {{
							top: calc(14% + 240px);
						}}
					}}
				</style>
				<div class="tour-backdrop"></div>
				<div class="tour-card">
					<span class="tour-progress">STEP {step_index + 1} OF {len(TOUR_STEPS)}</span>
					<h3>{html.escape(step['title'])}</h3>
					<p>{html.escape(step['body'])}</p>
				</div>
			""",
			unsafe_allow_html=True,
		)
		st.markdown("<div class='tour-controls'>", unsafe_allow_html=True)
		controls = st.columns([1, 1, 1])
		skip_clicked = controls[0].button("Skip tour", key=f"tour_skip_{step_index}")
		back_clicked = controls[1].button(
			"Back", disabled=step_index == 0, key=f"tour_back_{step_index}"
		)
		next_label = "Next" if step_index < len(TOUR_STEPS) - 1 else "Finish"
		next_clicked = controls[2].button(next_label, key=f"tour_next_{step_index}")
		st.markdown("</div>", unsafe_allow_html=True)
		if skip_clicked:
			st.session_state["tour_done"] = True
			st.session_state["tour_step"] = 0
		elif back_clicked:
			st.session_state["tour_step"] = max(0, step_index - 1)
		elif next_clicked:
			if step_index < len(TOUR_STEPS) - 1:
				st.session_state["tour_step"] = step_index + 1
			else:
				st.session_state["tour_done"] = True
				st.session_state["tour_step"] = 0


if not st.session_state.get("tour_done", False):
	_render_tour_overlay()

PERSONA_OPTIONS: list[tuple[str, str]] = [
	("Patient", "patient"),
	("Payer", "payer"),
	("Provider", "provider"),
]

LEVEL_OPTIONS: list[tuple[str, str]] = [
	("Grade 4", "grade4"),
	("Grade 6", "grade6"),
	("Grade 8", "grade8"),
	("Pro", "pro"),
]

GLOSSARY: dict[str, str] = {
	"EOB": "Explanation of Benefits (EOB): summary of how a claim was processed.",
	"Allowed Amount": "The maximum the plan says is payable for a covered service.",
	"Deductible": "Amount you pay for covered care before the plan starts to pay.",
	"Coinsurance": "Percentage of costs you pay after the deductible is met.",
	"OOP": "Out-of-pocket (OOP): what you pay in a year before hitting the limit.",
	"Amount Billed": "Total dollars the provider charged before plan adjustments.",
	"Insurer Paid": "What the health plan paid the provider for the service.",
	"Adjustments": "Discounts or corrections applied under plan rules or contracts.",
	"Patient Responsibility": "What the patient owes after payments and adjustments.",
}


def _option_value(label: str, options: list[tuple[str, str]]) -> str:
	for display, value in options:
		if display == label:
			return value
	return options[0][1]


def _label_with_tooltip(label: str | None) -> str:
	if not label:
		return "—"
	definition = GLOSSARY.get(label)
	safe_label = html.escape(label)
	if not definition:
		return safe_label
	safe_definition = html.escape(definition)
	return (
		f"{safe_label} "
		f"<span style='color:#2563eb;cursor:help;' title='{safe_definition}'>ℹ️</span>"
	)


upload_tab, dashboard_tab, review_tab, actions_tab = st.tabs(["Upload", "Dashboard", "Review", "Actions"])

with upload_tab:
	st.header("📤 Upload EOB")
	st.markdown("Drop a PDF, DOCX, or image file below. Files are uploaded to the backend and text/tables are extracted and redacted.")
	uploaded_file = st.file_uploader(
		"Upload EOB (drag and drop)",
		type=["pdf", "docx", "png", "jpg"],
		accept_multiple_files=False,
		key="eob_uploader",
	)

	if uploaded_file is not None:
		st.write(f"Selected: **{uploaded_file.name}** — {uploaded_file.type or 'unknown type'} — {uploaded_file.size} bytes")

		# Client-side preview before upload
		filename_lower = (uploaded_file.name or "").lower()
		try:
			file_bytes = uploaded_file.getvalue()
		except Exception:
			file_bytes = None

		if file_bytes:
			if (uploaded_file.type or "").startswith("image/") or filename_lower.endswith(('.png', '.jpg', '.jpeg')):
				# image preview
				try:
					st.image(file_bytes, caption="Preview", use_column_width=True)
				except Exception:
					st.caption("Unable to render image preview.")
			elif filename_lower.endswith('.pdf'):
				# embed PDF via data URL so browser's PDF viewer shows it (no external libs needed)
				import base64 as _base64

				b64 = _base64.b64encode(file_bytes).decode('ascii')
				pdf_html = f"<iframe src='data:application/pdf;base64,{b64}' width='100%' height='520px' style='border: none;'></iframe>"
				st_components.html(pdf_html, height=520)
			else:
				# DOCX or unknown types — no in-browser preview
				st.info("Preview not available for this file type. You can upload to extract text and tables.")
		upload_cols = st.columns([1, 1])
		with upload_cols[0]:
			if st.button("Upload to backend", key="upload_eob_button"):
				# prepare multipart file payload
				file_bytes = uploaded_file.getvalue()
				files_param = None
				if uploaded_file.type:
					files_param = {"file": (uploaded_file.name, file_bytes, uploaded_file.type)}
				else:
					files_param = {"file": (uploaded_file.name, file_bytes)}

				with st.spinner("Uploading and extracting (may use OCR)..."):
					data, error = request_json("POST", f"{api_base}/upload_eob", files=files_param)

				if error:
					st.error(f"Upload failed: {error}")
				elif data:
					# store last upload
					st.session_state["last_upload"] = data
					doc_id = data.get("doc_id")
					pages = data.get("pages")
					notes = data.get("notes") or []
					preview = data.get("preview", {})
					if doc_id:
						doc_id_str = str(doc_id)
						st.session_state["active_doc_id"] = doc_id_str
						st.session_state["current_doc_id"] = doc_id_str
						st.session_state["explain_doc_id"] = doc_id_str
						st.session_state["sim_doc_id"] = doc_id_str

					card_html = (
						"<div style='padding:14px;border-radius:10px;background:linear-gradient(90deg,#ecfeff,#f0f9ff);border:1px solid #c7f9f2;'>"
						f"<div style='font-weight:700;font-size:1.05rem;color:#064e3b;'>Upload successful</div>"
						f"<div style='margin-top:6px;color:#0f172a;'>Document: <code>{html.escape(str(doc_id))}</code></div>"
						f"<div style='margin-top:4px;color:#0f172a;'>Pages: {html.escape(str(pages))}</div>"
						"</div>"
					)
					st.markdown(card_html, unsafe_allow_html=True)

					# show preview rows (if present)
					rows = preview.get("rows") if isinstance(preview, dict) else None
					if rows:
						st.subheader("Preview rows")
						preview_table = ["<table style='width:100%;border-collapse:collapse;margin-top:0.5rem;'>",
										 "<thead><tr><th style='text-align:left;padding:6px;color:#0f172a;'>CPT / Description</th>",
										 "<th style='text-align:right;padding:6px;color:#0f172a;'>Amount</th></tr></thead>",
										 "<tbody>"]
						for r in rows[:6]:
							desc = html.escape(str(r.get("description") or r.get("cpt") or ""))
							amount = format_currency(r.get("billed") or r.get("allowed") or r.get("insurer_paid"))
							preview_table.append(f"<tr><td style='padding:6px;color:#1f2937;'>{desc}</td><td style='padding:6px;text-align:right;color:#0f172a;font-variant-numeric:tabular-nums;'>{amount}</td></tr>")
						preview_table.append("</tbody></table>")
						st.markdown("".join(preview_table), unsafe_allow_html=True)

					# show text snippets if present
					snippets = preview.get("text_snippets") if isinstance(preview, dict) else None
					if snippets:
						st.subheader("Text snippets")
						for s in snippets[:3]:
							st.caption(s)

					# OCR unavailable tip
					if any(("OCR unavailable" in str(n) or "ocr unavailable" in str(n).lower()) for n in notes):
						st.warning("OCR unavailable for this file. Try uploading a PDF with an embedded text layer, or paste text manually in Actions → Upload & Redact.")

						# If no structured rows were detected, offer a Manual Entry form
						if not rows:
							with st.expander("Manual entry (no table detected)", expanded=True):
								st.markdown("Provide the totals (or per-line items) so the app can continue analysis.")
								st.info("Manual entry will be stored for this session and used for Explain; results depend on the numbers you provide.")
								with st.form(key=f"manual_entry_form_{doc_id}"):
									total_billed = st.number_input("Total: Amount Billed", min_value=0.0, value=0.0, step=1.0, key=f"manual_total_billed_{doc_id}")
									total_allowed = st.number_input("Total: Allowed Amount", min_value=0.0, value=0.0, step=1.0, key=f"manual_total_allowed_{doc_id}")
									total_insurer = st.number_input("Total: Insurer paid", min_value=0.0, value=0.0, step=1.0, key=f"manual_total_insurer_{doc_id}")
									total_adjustments = st.number_input("Total: Adjustments (sum)", min_value=0.0, value=0.0, step=1.0, key=f"manual_total_adjust_{doc_id}")
									total_patient = st.number_input("Total: Patient responsibility", min_value=0.0, value=0.0, step=1.0, key=f"manual_total_patient_{doc_id}")
									st.markdown("---")
									st.markdown("Optional: enter up to 5 CPT/line items to include (leave CPT blank to skip row)")
									n_lines = st.number_input("Number of optional CPT lines", min_value=0, max_value=5, value=0, step=1, key=f"manual_lines_count_{doc_id}")
									optional_rows = []
									for i in range(int(n_lines)):
										c = st.text_input(f"Line {i+1} CPT", value="", key=f"manual_cpt_{doc_id}_{i}")
										b = st.number_input(f"Line {i+1} billed", min_value=0.0, value=0.0, step=1.0, key=f"manual_billed_{doc_id}_{i}")
										a = st.number_input(f"Line {i+1} allowed", min_value=0.0, value=0.0, step=1.0, key=f"manual_allowed_{doc_id}_{i}")
										p = st.number_input(f"Line {i+1} insurer paid", min_value=0.0, value=0.0, step=1.0, key=f"manual_insurer_{doc_id}_{i}")
										pr = st.number_input(f"Line {i+1} patient resp", min_value=0.0, value=0.0, step=1.0, key=f"manual_patient_{doc_id}_{i}")
										optional_rows.append({
											"line_id": f"L{i+1}",
											"page": 1,
											"cell_id": f"manual:R{i+1}C1",
											"cpt": c or "",
											"billed": float(b),
											"allowed": float(a),
											"insurer_paid": float(p),
											"adjustments": [],
											"patient_resp": float(pr),
										})
									submit_manual = st.form_submit_button("Submit manual entry")
									if submit_manual:
										# build rows: include optional rows and a TOTAL row
										rows_payload = []
										for r in optional_rows:
											if (r.get("cpt") or "").strip():
												rows_payload.append(r)
										total_row = {
											"line_id": "TOTAL",
											"page": 1,
											"cell_id": "manual:TOTAL",
											"cpt": "",
											"modifier": "",
											"billed": float(total_billed),
											"allowed": float(total_allowed),
											"insurer_paid": float(total_insurer),
											"adjustments": [{"type": "manual", "amount": float(total_adjustments)}] if float(total_adjustments) else [],
											"patient_resp": float(total_patient),
										}
										rows_payload.append(total_row)
										# call backend endpoint to persist
										# use the active session ID when persisting manual entries
										sess = current_session_id or ""
										payload_send = {"session_id": sess, "doc_id": doc_id, "rows": rows_payload}
										resp, err = request_json("POST", f"{api_base}/session/manual_entry", json=payload_send)
										if err:
											st.error(f"Unable to save manual entry: {err}")
										else:
											st.success("Manual entry saved and will be used for analysis.")
											# set session state so Explain/Simulate default to this doc
											st.session_state["current_doc_id"] = doc_id
											st.session_state["explain_doc_id"] = doc_id
											st.session_state["sim_doc_id"] = doc_id
											st.session_state["manual_entry_used"] = True
											st.markdown("**Manual entry used; results depend on provided numbers.**")

					# toggle to set as current doc
					use_as_current = st.checkbox("Use this as current document", key="use_upload_as_current")
					if use_as_current and doc_id:
						st.session_state["current_doc_id"] = doc_id
						# update related inputs
						st.session_state["explain_doc_id"] = doc_id
						st.session_state["sim_doc_id"] = doc_id
						st.session_state["sidebar_doc_id"] = doc_id
						st.success(f"Set {doc_id} as current document")

					# option to save as favorite doc for this session (pins default)
					save_fav = st.checkbox("Save as favorite doc (pin as default)", key=f"save_fav_{doc_id}")
					if save_fav and doc_id:
						st.session_state["favorite_doc_id"] = doc_id
						st.success(f"Pinned {doc_id} as favorite for this session")

		with upload_cols[1]:
			st.info("Accepted formats: .pdf, .docx, .png, .jpg. Max file size enforced by backend (15MB).")


	with dashboard_tab:
		st.header("📊 Session Dashboard")
		st.markdown("Aggregate metrics across all uploaded EOBs for the selected session.")

		default_dashboard_session = st.session_state.get("dashboard_session_id", current_session_id or "")
		session_input = st.text_input("Session ID", value=default_dashboard_session, key="dashboard_session_id")
		if not session_input:
			st.info("Enter a Session ID (from the Benefits UI or upload response) to load dashboard data.")
		else:
			with st.spinner("Loading session claims..."):
				resp, err = request_json("GET", f"{api_base}/session/claims", params={"session_id": session_input})
			if err:
				st.error(f"Unable to load session claims: {err}")
			else:
				data_rows = resp.get("rows", []) if isinstance(resp, dict) else []
				docs = resp.get("docs", []) if isinstance(resp, dict) else []

				if not data_rows:
					st.warning("No structured claim rows found for this session.")
				else:
					# try to import pandas and altair
					try:
						import pandas as pd  # type: ignore
					except Exception:
						pd = None
					try:
						import altair as alt  # type: ignore
					except Exception:
						alt = None

					# normalize rows into DataFrame-like list
					rows_norm = []
					for r in data_rows:
						rows_norm.append({
							"doc_id": r.get("doc_id"),
							"cpt": r.get("cpt") or "",
							"description": r.get("description") or "",
							"billed": float(r.get("billed") or 0.0),
							"allowed": float(r.get("allowed") or 0.0),
							"insurer_paid": float(r.get("insurer_paid") or 0.0),
							"patient_resp": float(r.get("patient_resp") or 0.0),
							"adjustments": r.get("adjustments") or [],
						})

					# aggregate adjustments numeric sum when possible
					def sum_adjustments(adjs):
						s = 0.0
						for a in (adjs or []):
							try:
								val = float(str(a).replace("$", "").replace(",", ""))
								s += val
							except Exception:
								continue
						return s

					for rr in rows_norm:
						rr["adjustments_sum"] = sum_adjustments(rr.get("adjustments"))

					# create pandas DataFrame if available
					if pd is not None:
						df = pd.DataFrame(rows_norm)

						# Stacked bar per document
						doc_agg = df.groupby("doc_id")[ ["billed", "allowed", "adjustments_sum", "insurer_paid", "patient_resp"] ].sum().reset_index()
						doc_melt = doc_agg.melt(id_vars=["doc_id"], var_name="kind", value_name="amount")
						if alt is not None:
							chart = (
								alt.Chart(doc_melt)
								.mark_bar()
								.encode(
									x=alt.X("doc_id:N", title="Document"),
									y=alt.Y("amount:Q", title="Amount"),
									color=alt.Color("kind:N", title="Category"),
									tooltip=[alt.Tooltip("kind:N"), alt.Tooltip("amount:Q", format="$,.2f")],
								)
								.properties(height=320)
							)
							st.altair_chart(chart, use_container_width=True)
							# export buttons for aggregated docs
							try:
								csv_bytes = doc_agg.to_csv(index=False).encode("utf-8")
								st.download_button("Download docs CSV", data=csv_bytes, file_name=f"{session_input}_docs_agg.csv", mime="text/csv")
							except Exception:
								pass
						else:
							st.write("Stacked view requires Altair — showing separate bars per metric.")
							st.bar_chart(doc_agg.set_index("doc_id"))
							try:
								csv_bytes = doc_agg.to_csv(index=False).encode("utf-8")
								st.download_button("Download docs CSV", data=csv_bytes, file_name=f"{session_input}_docs_agg.csv", mime="text/csv")
							except Exception:
								pass

						# Top CPTs by allowed amount
						cpt_agg = df.groupby("cpt")["allowed"].sum().reset_index().sort_values("allowed", ascending=False).head(10)
						if alt is not None:
							cpt_chart = (
								alt.Chart(cpt_agg)
								.mark_bar()
								.encode(
									x=alt.X("allowed:Q", title="Allowed"),
									y=alt.Y("cpt:N", sort="-x", title="CPT"),
									tooltip=[alt.Tooltip("cpt:N"), alt.Tooltip("allowed:Q", format="$,.2f")],
								)
								.properties(height=300)
							)
							st.subheader("Top CPTs by allowed amount")
							st.altair_chart(cpt_chart, use_container_width=True)
							try:
								csv_bytes = cpt_agg.to_csv(index=False).encode("utf-8")
								st.download_button("Download CPTs CSV", data=csv_bytes, file_name=f"{session_input}_top_cpts.csv", mime="text/csv")
							except Exception:
								pass
						else:
							st.subheader("Top CPTs by allowed amount")
							st.bar_chart(cpt_agg.set_index("cpt"))
							try:
								csv_bytes = cpt_agg.to_csv(index=False).encode("utf-8")
								st.download_button("Download CPTs CSV", data=csv_bytes, file_name=f"{session_input}_top_cpts.csv", mime="text/csv")
							except Exception:
								pass

						# Providers by patient responsibility — fallback to doc filename
						doc_meta = {d.get("doc_id"): d.get("filename") for d in (docs or [])}
						df["filename"] = df["doc_id"].map(doc_meta)
						prov_agg = df.groupby("filename")["patient_resp"].sum().reset_index().sort_values("patient_resp", ascending=False).head(10)
						st.subheader("Providers / Files by patient responsibility")
						if alt is not None:
							prov_chart = (
								alt.Chart(prov_agg)
								.mark_bar()
								.encode(
									x=alt.X("patient_resp:Q", title="Patient responsibility"),
									y=alt.Y("filename:N", sort="-x", title="Provider / File"),
									tooltip=[alt.Tooltip("filename:N"), alt.Tooltip("patient_resp:Q", format="$,.2f")],
								)
							)
							st.altair_chart(prov_chart, use_container_width=True)
							try:
								csv_bytes = prov_agg.to_csv(index=False).encode("utf-8")
								st.download_button("Download providers CSV", data=csv_bytes, file_name=f"{session_input}_providers.csv", mime="text/csv")
							except Exception:
								pass
						else:
							st.bar_chart(prov_agg.set_index("filename"))
							try:
								csv_bytes = prov_agg.to_csv(index=False).encode("utf-8")
								st.download_button("Download providers CSV", data=csv_bytes, file_name=f"{session_input}_providers.csv", mime="text/csv")
							except Exception:
								pass

						# Reconciliation: totals + anomalies
						st.markdown("---")
						if st.button("Run reconciliation", key="run_reconcile"):
							with st.spinner("Running reconciliation..."):
								resp, err = request_json("GET", f"{api_base}/reconcile/session/{session_input}")
								if err:
									st.error(f"Reconciliation failed: {err}")
								else:
									st.session_state["last_reconcile"] = resp

						last_recon = st.session_state.get("last_reconcile")
						if last_recon and isinstance(last_recon, dict) and last_recon.get("session_id") == session_input:
							st.subheader("Reconciliation summary")
							tot = last_recon.get("totals", {})
							cols = st.columns(5)
							cols[0].metric("Billed", format_currency(tot.get("billed")))
							cols[1].metric("Allowed", format_currency(tot.get("allowed")))
							cols[2].metric("Insurer paid", format_currency(tot.get("insurer_paid")))
							cols[3].metric("Adjustments", format_currency(tot.get("adjustments")))
							cols[4].metric("Patient resp", format_currency(tot.get("patient_resp")))

							anoms = last_recon.get("anomalies", []) or []
							if anoms:
								st.markdown("**Anomalies detected**")
								# render compact table: type, summary
								rows_tbl = []
								for a in anoms:
									type_ = a.get("type")
									if type_ == "duplicate_line_id":
										summary = f"line {a.get('line_id')} in docs: {', '.join(a.get('docs', []))}"
									elif type_ == "cpt_modifier_mismatch":
										variants = a.get("variants", [])
										summary = "; ".join([f"mods={v.get('modifiers')} -> {', '.join(v.get('docs', []))}" for v in variants])
									elif type_ == "missing_adjustments":
										summary = f"doc {a.get('doc_id')} has {len(a.get('rows', []))} rows missing adjustments"
									else:
										summary = str(a)
									rows_tbl.append({"type": type_, "summary": summary})

								# prefer altair if available
								try:
									import pandas as pd  # type: ignore
									df_an = pd.DataFrame(rows_tbl)
									try:
										import altair as alt  # type: ignore
										st.altair_chart(alt.Chart(df_an).mark_bar().encode(x=alt.X('type:N', sort=None), y=alt.Y('count()', title='Count'), tooltip=['type', 'summary']).properties(height=150), use_container_width=True)
									except Exception:
										st.table(df_an)
								except Exception:
									# fallback textual
									for r in rows_tbl:
										st.write(f"- {r['type']}: {r['summary']}")
							else:
								st.caption("No anomalies detected.")

						# YTD OOP progress gauge using loaded profile if available
						profile = st.session_state.get("profile_data")
						if profile:
							oop_max = float(profile.get("oop_max") or 0.0)
							oop_rem = float(profile.get("oop_remaining") or 0.0)
							if oop_max > 0:
								prog = max(0.0, min(1.0, (oop_max - oop_rem) / oop_max))
								st.subheader("YTD OOP progress")
								st.progress(prog)
								st.write(f"{int(prog*100)}% — {format_currency(oop_max - oop_rem)} of {format_currency(oop_max)}")

								# What-if future spend slider
								more = st.slider("What-if future allowed spend", 0, 5000, 0, step=50, key="whatif_spend")
								if more is not None:
									# compute additional patient responsibility from `more`
									ded_rem = float(profile.get("deductible_remaining") or 0.0)
									coins = float(profile.get("coinsurance") or 0.0)
									remaining = float(profile.get("oop_remaining") or 0.0)

									# helper to compute patient responsibility for an allowed amount
									def patient_resp_from_allowed(allowed_amt: float) -> float:
										applied_ded = min(allowed_amt, ded_rem)
										after_ded = max(0.0, allowed_amt - applied_ded)
										coins_part = after_ded * coins
										return applied_ded + coins_part

									extra = patient_resp_from_allowed(float(more))
									proj_remaining = max(0.0, remaining - extra)
									if proj_remaining <= 0:
										st.success(f"At ${more:,.0f} more allowed spend, you reach the OOP max.")
									else:
										# compute required allowed spend to reach OOP
										if coins == 0:
											# only deductible contributes
											needed = max(0.0, min(ded_rem, remaining))
											if needed <= 0:
												st.info("Additional allowed spend won't reduce OOP remaining with 0% coinsurance after deductible.")
											else:
												st.info(f"You need approximately ${needed:,.0f} allowed spend to hit the OOP max.")
										else:
											if remaining <= ded_rem:
												req = remaining
											else:
												req = ded_rem + (remaining - ded_rem) / coins
											st.info(f"You would need about ${req:,.0f} allowed spend to reach OOP max.")
							else:
								st.info("OOP max not set in profile; load a profile with OOP max to see progress.")
					else:
						st.warning("Pandas not available in the frontend env; cannot render detailed charts.")

		st.divider()
		st.header("🩺 Benefits (Plan profile)")
		st.markdown("Use a stored plan profile to pre-fill simulation inputs and keep common plan values on file for this session.")
		benefit_cols = st.columns(2)
		with benefit_cols[0]:
			session_default = st.session_state.get("profile_session_id_input", current_session_id or "")
			session_id_input = st.text_input("Session ID", value=session_default, key="profile_session_id_input")
			plan_year_start = st.text_input("Plan year start (YYYY-MM-DD)", value="", key="plan_year_start")
			plan_name = st.text_input("Plan name", value="", key="plan_name")
			st.markdown("**Deductible**")
			deductible_individual = st.number_input("Deductible (individual)", min_value=0.0, value=0.0, step=50.0, key="deductible_individual")
			deductible_remaining_b = st.number_input("Deductible remaining", min_value=0.0, value=0.0, step=50.0, key="deductible_remaining_b")
		with benefit_cols[1]:
			coinsurance_b = st.number_input("Coinsurance", min_value=0.0, max_value=1.0, value=0.2, step=0.05, key="coinsurance_b")
			oop_max_b = st.number_input("OOP max", min_value=0.0, value=0.0, step=50.0, key="oop_max_b")
			oop_remaining_b = st.number_input("OOP remaining", min_value=0.0, value=0.0, step=50.0, key="oop_remaining_b")
			st.markdown("**Copays**")
			copay_primary = st.number_input("Primary care copay", min_value=0.0, value=0.0, step=1.0, key="copay_primary")
			copay_specialist = st.number_input("Specialist copay", min_value=0.0, value=0.0, step=1.0, key="copay_specialist")
			copay_er = st.number_input("ER copay", min_value=0.0, value=0.0, step=1.0, key="copay_er")

		save_cols = st.columns([1, 1])
		with save_cols[0]:
			if st.button("Save plan profile", key="save_plan_profile"):
				if not session_id_input or not session_id_input.strip():
					st.error("Session ID is required to save a profile.")
				else:
					payload = {
						"session_id": session_id_input.strip(),
						"plan_year_start": plan_year_start or None,
						"plan_name": plan_name or None,
						"deductible_individual": deductible_individual or None,
						"deductible_remaining": deductible_remaining_b or None,
						"coinsurance": coinsurance_b or None,
						"oop_max": oop_max_b or None,
						"oop_remaining": oop_remaining_b or None,
						"copays": {"primary": copay_primary, "specialist": copay_specialist, "er": copay_er},
					}
					data, error = request_json("POST", f"{api_base}/profile/set", json=payload)
					if error:
						st.error(f"Unable to save profile: {error}")
					else:
						st.session_state["profile_session_id"] = session_id_input.strip()
						st.success("Profile saved.")
						st.session_state["profile_data"] = data.get("profile") if isinstance(data, dict) else None
		with save_cols[1]:
			if st.button("Load profile", key="load_plan_profile"):
				if not session_id_input or not session_id_input.strip():
					st.error("Provide a session_id to load a profile.")
				else:
					prof, err = request_json("GET", f"{api_base}/profile/get", params={"session_id": session_id_input.strip()})
					if err:
						st.error(f"Unable to load profile: {err}")
					else:
						profile = prof.get("profile") if isinstance(prof, dict) else None
						if profile:
							st.session_state["profile_session_id"] = session_id_input.strip()
							st.session_state["profile_data"] = profile
							# populate simulation defaults
							st.session_state["deductible_remaining_input"] = profile.get("deductible_remaining") or st.session_state.get("deductible_remaining_input", 0.0)
							st.session_state["coinsurance_input"] = profile.get("coinsurance") or st.session_state.get("coinsurance_input", 0.2)
							st.session_state["oop_remaining_input"] = profile.get("oop_remaining") or st.session_state.get("oop_remaining_input", 0.0)
							st.success("Profile loaded and simulation defaults updated.")

		# Plan snapshot
		profile_data = st.session_state.get("profile_data")
		if profile_data:
			st.divider()
			st.subheader("Plan snapshot")
			oop_max_val = float(profile_data.get("oop_max") or 0.0)
			oop_rem_val = float(profile_data.get("oop_remaining") or 0.0)
			if oop_max_val and oop_max_val > 0:
				progress_val = max(0.0, min(1.0, (oop_max_val - oop_rem_val) / oop_max_val))
				# Prefer interactive Plotly donut/gauge if available, otherwise fall back to SVG
				try:
					import plotly.graph_objects as go  # type: ignore
					rest = 1.0 - progress_val
					fig = go.Figure(
						go.Pie(
							values=[progress_val, rest],
							hole=0.65,
							marker=dict(colors=["#06b6d4", "#e6eef6"]),
							textinfo="none",
							sort=False,
						)
					)
					fig.update_layout(
						showlegend=False,
						margin=dict(t=0, b=0, l=0, r=0),
						annotations=[
							{
								"text": f"{int(progress_val*100)}%",
								"x": 0.5,
								"y": 0.5,
								"font": {"size": 20, "color": "#0f172a"},
								"showarrow": False,
							}
						],
					)
					st.plotly_chart(fig, use_container_width=True)
					st.write(f"{int(progress_val*100)}% — {format_currency(oop_max_val - oop_rem_val)} of {format_currency(oop_max_val)}")
					# allow exporting the donut as PNG or HTML
					try:
						img = fig.to_image(format="png")
						st.download_button("Download OOP chart PNG", data=img, file_name=f"{session_input}_oop_chart.png", mime="image/png")
					except Exception:
						# fallback to HTML export
						html_blob = fig.to_html().encode("utf-8")
						st.download_button("Download OOP chart (HTML)", data=html_blob, file_name=f"{session_input}_oop_chart.html", mime="text/html")
				except Exception:
					# fallback SVG
					radius = 52
					stroke = 12
					import math as _math
					circ = 2 * _math.pi * radius
					filled = progress_val * circ
					svg = f'''<div style="display:flex;align-items:center;gap:18px;">
					  <svg width="140" height="140" viewBox="0 0 140 140" xmlns="http://www.w3.org/2000/svg">
					    <defs>
					      <linearGradient id="g1" x1="0%" y1="0%" x2="100%" y2="0%">
					        <stop offset="0%" stop-color="#06b6d4" />
					        <stop offset="100%" stop-color="#60a5fa" />
					      </linearGradient>
					    </defs>
					    <g transform="translate(70,70)">
					      <circle r="{radius}" fill="none" stroke="#e6eef6" stroke-width="{stroke}" />
					      <circle r="{radius}" fill="none" stroke="url(#g1)" stroke-width="{stroke}" stroke-linecap="round"
					        stroke-dasharray="{filled} {circ - filled}" transform="rotate(-90)" />
					      <text x="0" y="6" text-anchor="middle" font-size="20" fill="#0f172a" font-weight="700">{int(progress_val*100)}%</text>
					    </g>
					  </svg>
					  <div style="max-width:340px;">
					    <div style="font-weight:700;color:#0f172a;font-size:1.05rem;">Out-of-pocket progress</div>
					    <div style="color:#475569;margin-top:6px;">{int(progress_val*100)}% of OOP reached ({format_currency(oop_max_val - oop_rem_val)} of {format_currency(oop_max_val)})</div>
					  </div>
					</div>'''
					st_components.html(svg, height=160)
			else:
				st.write("OOP progress: N/A")
			chip_cols = st.columns([1, 1, 1])
			chip_cols[0].markdown(f"**Coinsurance:** {profile_data.get('coinsurance')} ")
			chip_cols[1].markdown(f"**Deductible remaining:** {format_currency(profile_data.get('deductible_remaining'))}")
			copays = profile_data.get("copays") or {}
			chip_cols[2].markdown(f"**Copays:** primary {format_currency(copays.get('primary'))}, spec {format_currency(copays.get('specialist'))}, ER {format_currency(copays.get('er'))}")


with review_tab:
	header_col, score_col, privacy_col = st.columns([0.55, 0.25, 0.2])
	with header_col:
		st.header("🧮 Explain")
		active_doc = st.session_state.get("active_doc_id")
		if active_doc:
			chip_html = (
				f"<div style='margin-top:8px;'>"
				f"<span style='display:inline-block;padding:6px 12px;border-radius:999px;background:#047857;color:#ecfdf5;font-weight:600;'>"
				f"Active doc: {html.escape(str(active_doc))}</span>"
				"</div>"
			)
			st.markdown(chip_html, unsafe_allow_html=True)
	score_placeholder = score_col.empty()
	privacy_placeholder = privacy_col.empty()
	# default to favorite doc, then most recent upload, then current_doc_id
	default_doc = active_doc or st.session_state.get("favorite_doc_id") or (
		(st.session_state.get("last_upload") or {}).get("doc_id") if isinstance(st.session_state.get("last_upload"), dict) else None
	) or st.session_state.get("current_doc_id", "EOB-001")

	explain_doc_input = st.text_input(
		"Document ID",
		value=default_doc,
		key="explain_doc_id",
	)
	current_doc_id = (explain_doc_input or "").strip() or st.session_state.get("current_doc_id", "EOB-001")
	st.session_state["current_doc_id"] = current_doc_id

	# allow pinning the selected doc as favorite from the Explain tab
	pin_col, pin_col2 = st.columns([0.25, 0.75])
	with pin_col:
		pin_toggle = st.checkbox("Save as favorite doc", value=(st.session_state.get("favorite_doc_id") == current_doc_id), key="save_fav_explain")
		if pin_toggle:
			st.session_state["favorite_doc_id"] = current_doc_id
	with pin_col2:
		if st.session_state.get("favorite_doc_id"):
			fav = st.session_state.get("favorite_doc_id")
			st.caption(f"Favorite: {fav}")
	privacy_doc = st.session_state.get("privacy_redacted_doc")
	if privacy_doc:
		privacy_placeholder.markdown(_PRIVACY_BADGE_HTML, unsafe_allow_html=True)
	else:
		privacy_placeholder.empty()
	persona_col, level_col, language_col = st.columns(3)
	persona_choice = persona_col.selectbox(
		"Persona",
		[label for label, _ in PERSONA_OPTIONS],
		index=0,
		key="explain_persona",
	)
	level_choice = level_col.selectbox(
		"Reading level",
		[label for label, _ in LEVEL_OPTIONS],
		index=1,
		key="explain_level",
	)
	language_choice = language_col.selectbox(
		"Language",
		["EN", "ES", "HI"],
		index=0,
		key="explain_language",
	)
	persona_value = _option_value(persona_choice, PERSONA_OPTIONS)
	level_value = _option_value(level_choice, LEVEL_OPTIONS)
	language_value = language_choice.lower()
	if st.button("Explain", key="explain_button"):
		params = {"persona": persona_value, "level": level_value}
		params["language"] = language_value
		data, error = request_json(
			"GET", f"{api_base}/explain/{current_doc_id}", params=params
		)
		if error:
			st.error(f"Unable to retrieve explanation: {error}")
		elif data:
			# persist latest explain payload in session state for audit / UI
			st.session_state["explain_data"] = data
			verifiability = float(data.get("verifiability_score", 0.0))

			if verifiability >= 0.9:
				badge_color, badge_label, text_color = "#16a34a", "High", "#ffffff"
			elif verifiability >= 0.75:
				badge_color, badge_label, text_color = "#facc15", "Medium", "#0f172a"
			else:
				badge_color, badge_label, text_color = "#dc2626", "Low", "#ffffff"

			score_placeholder.markdown(
				f"<div style='display:flex;justify-content:flex-end;margin-top:18px;'>"
				f"<span style='display:inline-block;padding:4px 12px;border-radius:999px;"
				f"background-color:{badge_color};color:{text_color};font-weight:600;'>"
				f"V-Score {badge_label} · {verifiability:.2f}</span></div>",
				unsafe_allow_html=True,
			)

			# gather risk flags early (used for provider persona conditional note)
			risk_flags = data.get("risk_flags") or []

			takeaway_text = data.get("takeaway")
			if takeaway_text:
				# extract up to two sentences for a compact bold takeaway
				import re

				parts = re.split(r'(?<=[.!?])\s+', takeaway_text.strip())
				two_sent = " ".join(parts[:2]) if parts else takeaway_text

				# persona and reading chips (simple inline chips)
				persona_label = persona_choice or "Patient"
				reading_label = level_choice or "Intermediate"

				# conditional bullet: payer -> policy reference; provider -> coding note if risk exists
				bullet_html = ""
				if persona_value == "payer":
					policy_ref = data.get("policy_reference") or data.get("policy_notes")
					if not policy_ref:
						policy_ref = "Applied deductible first, then 20% coinsurance"
					bullet_html = html.escape(str(policy_ref))
				elif persona_value == "provider":
					if risk_flags:
						first_flag = risk_flags[0]
						flag_label = first_flag.get("label") or "Coding risk"
						coding_note = f"Coding note: {flag_label} — verify CPTs/units and modifiers."
						bullet_html = html.escape(str(coding_note))

				# render the bold two-sentence takeaway
				st.markdown(f"**{html.escape(two_sent)}**")

				# render small chips for persona and reading level
				chip_html = (
					f"<div style='display:flex;gap:8px;margin-top:6px;'>"
					f"<span style='display:inline-block;padding:6px 10px;border-radius:999px;background:#eef2ff;color:#1e3a8a;font-weight:600;'>Persona: {html.escape(persona_label)}</span>"
					f"<span style='display:inline-block;padding:6px 10px;border-radius:999px;background:#f1f5f9;color:#0f172a;font-weight:600;'>Reading: {html.escape(reading_label)}</span>"
					f"</div>"
				)
				st.markdown(chip_html, unsafe_allow_html=True)

				# render conditional bullet
				if bullet_html:
					st.markdown(f"<ul style='margin-top:8px;color:#475569;'><li>{bullet_html}</li></ul>", unsafe_allow_html=True)

			graph_data, graph_error = request_json("GET", f"{api_base}/egraph/{current_doc_id}")

			with st.expander("Glossary", expanded=False):
				for term, definition in GLOSSARY.items():
					st.markdown(f"**{term}:** {definition}")

			breakdown = data.get("breakdown", []) or []
			if breakdown:
				summary_cols = st.columns(3)
				summary_cols[0].metric("Document", current_doc_id)
				summary_cols[1].metric("Persona", persona_choice)
				summary_cols[2].metric("Reading level", level_choice)

				table_rows = []
				for item in breakdown:
					rendered_label = _label_with_tooltip(item.get("label"))
					amount = format_currency(item.get("value"))
					table_rows.append(
						(
							rendered_label,
							f"<span style='display:inline-block;width:6rem;text-align:right;font-variant-numeric:tabular-nums;'>{amount}</span>",
						)
					)
				table_html = [
					"<table style='width:100%;border-collapse:collapse;margin-top:0.75rem;'>",
					"<thead><tr><th style='text-align:left;padding:6px;color:#0f172a;'>Item</th><th style='text-align:right;padding:6px;color:#0f172a;'>Amount</th></tr></thead>",
					"<tbody>",
				]
				for label_html, value_html in table_rows:
					table_html.append(
						f"<tr><td style='padding:6px;font-weight:600;color:#1f2937;'>{label_html}</td><td style='padding:6px;text-align:right;color:#111827;'>{value_html}</td></tr>"
					)
				table_html.append("</tbody>")
				table_html.append("</table>")
				st.markdown("".join(table_html), unsafe_allow_html=True)

				# --- Visual: single-document breakdown donut ---
				try:
					# helper to pick amounts from breakdown by matching label keys
					def _find_amount(bd, keys):
						for item in (bd or []):
							lbl = (item.get("label") or "").lower()
							for k in keys:
								if k in lbl:
									try:
										return float(item.get("value") or 0.0)
									except Exception:
										return 0.0
						# default when nothing matched
						return 0.0

					bd = breakdown
					billed_val = _find_amount(bd, ["billed", "amount billed", "amount"]) or 0.0
					insurer_val = _find_amount(bd, ["insurer", "insurer paid", "paid by insurer"]) or 0.0
					adjust_val = _find_amount(bd, ["adjust", "adjustments"]) or 0.0
					patient_val = _find_amount(bd, ["patient", "patient responsibility"]) or 0.0

					# fallback: derive patient from billed - insurer - adjustments when missing
					if not patient_val:
						try:
							patient_val = max(0.0, billed_val - insurer_val - adjust_val)
						except Exception:
							patient_val = 0.0

					labels = ["Billed", "Insurer Paid", "Adjustments", "Patient"]
					values = [billed_val, insurer_val, adjust_val, patient_val]

					# prefer plotly for interactive donut, fallback to Altair or Matplotlib, then simple write
					rendered = False
					try:
						import plotly.graph_objects as go  # type: ignore
						fig = go.Figure(go.Pie(labels=labels, values=values, hole=0.6, sort=False, marker=dict(colors=["#60a5fa", "#10b981", "#f97316", "#ef4444"])))
						fig.update_layout(margin=dict(t=0, b=0, l=0, r=0), showlegend=True)
						st.subheader("Document breakdown")
						st.plotly_chart(fig, use_container_width=True)
						rendered = True
					except Exception:
						try:
							import altair as alt  # type: ignore
							import pandas as pd  # type: ignore
							df = pd.DataFrame({"label": labels, "value": values})
							chart = alt.Chart(df).mark_arc(innerRadius=60).encode(
								theta=alt.Theta(field="value", type="quantitative"),
								color=alt.Color("label:N", legend=alt.Legend(title="Category")),
								tooltip=[alt.Tooltip("label:N"), alt.Tooltip("value:Q", format="$,.2f")],
							)
							st.subheader("Document breakdown")
							st.altair_chart(chart, use_container_width=True)
							rendered = True
						except Exception:
							try:
								import matplotlib.pyplot as plt  # type: ignore
								fig, ax = plt.subplots(figsize=(4, 3))
								colors = ["#60a5fa", "#10b981", "#f97316", "#ef4444"]
								ax.pie(values, labels=labels, colors=colors, wedgeprops=dict(width=0.4))
								ax.set(aspect="equal")
								st.subheader("Document breakdown")
								st.pyplot(fig)
								rendered = True
							except Exception:
								# simple textual fallback
								st.subheader("Document breakdown")
								st.write({labels[i]: values[i] for i in range(len(labels))})
					# caption with numeric breakdown
					try:
						amounts_text = " · ".join(f"{labels[i]}: {format_currency(values[i])}" for i in range(len(labels)))
						st.caption(amounts_text)
					except Exception:
						# ignore caption failures
						pass

					# provide download link for underlying explain JSON (separate try so failures don't hide above)
					try:
						st.download_button("Download explain JSON", data=json.dumps(data, indent=2), file_name=f"{current_doc_id}_explain.json", mime="application/json")
					except Exception:
						# ignore if download fails
						pass
				except Exception:
					# non-fatal: skip visuals if anything goes wrong
					pass

				# --- Visual: PSL Fair Bill vs Current patient responsibility (side-by-side) ---
				# show when a simulation has been run for this doc
				try:
					last_sim = st.session_state.get("last_simulation")
					last_doc = st.session_state.get("last_simulation_doc")
					if last_sim and last_doc and str(last_doc) == str(current_doc_id):
						try:
							fair = float((last_sim.get("details") or {}).get("fair_bill") or last_sim.get("fair_bill") or 0.0)
						except Exception:
							fair = 0.0
						try:
							patient_now = float(last_sim.get("expected_patient_resp") or last_sim.get("expected_patient") or 0.0)
						except Exception:
							patient_now = 0.0

						if fair or patient_now:
							# render side-by-side bars with plotly/altair/matplotlib fallbacks
							rendered2 = False
							try:
								import plotly.graph_objects as go  # type: ignore
								fig2 = go.Figure(data=[
									go.Bar(name="Fair Bill (PSL)", x=[""], y=[fair], marker_color="#2563eb"),
									go.Bar(name="Expected Patient", x=[""], y=[patient_now], marker_color="#ef4444"),
								])
								fig2.update_layout(barmode='group', title_text='PSL Fair Bill vs Expected Patient Responsibility', showlegend=True, margin=dict(t=30))
								st.plotly_chart(fig2, use_container_width=True)
								rendered2 = True
							except Exception:
								try:
									import altair as alt  # type: ignore
									import pandas as pd  # type: ignore
									df2 = pd.DataFrame({"scenario": ["Fair Bill (PSL)", "Expected Patient"], "amount": [fair, patient_now]})
									chart2 = alt.Chart(df2).mark_bar().encode(
										x=alt.X("scenario:N", sort=None),
										y=alt.Y("amount:Q"),
										color=alt.Color("scenario:N", legend=None),
										tooltip=[alt.Tooltip("scenario:N"), alt.Tooltip("amount:Q", format="$,.2f")],
									)
									st.subheader("PSL Fair Bill vs Expected Patient Responsibility")
									st.altair_chart(chart2, use_container_width=True)
									rendered2 = True
								except Exception:
									try:
										import matplotlib.pyplot as plt  # type: ignore
										fig3, ax3 = plt.subplots(figsize=(5, 2.5))
										ax3.bar([0, 1], [fair, patient_now], color=["#2563eb", "#ef4444"])
										ax3.set_xticks([0, 1])
										ax3.set_xticklabels(["Fair Bill (PSL)", "Expected Patient"], rotation=0)
										ax3.set_ylabel("Amount")
										st.subheader("PSL Fair Bill vs Expected Patient Responsibility")
										st.pyplot(fig3)
										rendered2 = True
									except Exception:
										# final fallback to textual
										st.subheader("PSL Fair Bill vs Expected Patient")
										st.write({"Fair Bill (PSL)": fair, "Expected Patient": patient_now})
							# caption under PSL chart with values and download link
							try:
								st.caption(f"Fair Bill (PSL): {format_currency(fair)} · Expected Patient: {format_currency(patient_now)}")
								try:
									st.download_button("Download explain JSON", data=json.dumps(data, indent=2), file_name=f"{current_doc_id}_explain.json", mime="application/json")
								except Exception:
									pass
							except Exception:
								# non-fatal: ignore failures rendering caption/download UI
								pass
					else:
						st.caption("PSL / patient comparison not available.")
				except Exception:
					pass

			warnings_list = data.get("warnings") or []
			if warnings_list:
				warning_text = " ".join(str(warning) for warning in warnings_list)
				st.markdown(
					f"<div style='background:#fef3c7;border:1px solid #facc15;padding:10px 14px;border-radius:8px;color:#92400e;font-weight:600;margin-top:0.75rem;'>"
					f"⚠️ {html.escape(warning_text)}"
					"</div>",
					unsafe_allow_html=True,
				)

			risk_flags = data.get("risk_flags") or []
			st.subheader("Risk flags")
			if risk_flags:
				severity_palette = {"high": "#dc2626", "medium": "#f97316", "low": "#22c55e"}
				for flag in risk_flags:
					severity = str(flag.get("severity", "")).lower()
					label = flag.get("label", "Risk")
					color = severity_palette.get(severity, "#6b7280")
					st.markdown(
						f"<div style='display:flex;align-items:center;margin-bottom:4px;'>"
						f"<span style='display:inline-block;width:10px;height:10px;border-radius:50%;"
						f"background-color:{color};margin-right:8px;'></span>"
						f"<span style='font-weight:600;'>{label}</span>"
						f"<span style='margin-left:6px;color:#475569;font-size:0.85rem;'>{severity.title() if severity else ''}</span>"
						f"</div>",
						unsafe_allow_html=True,
					)
			else:
				st.caption("No risk patterns detected.")

			st.subheader("Evidence graph")
			if graph_error:
				st.info(f"Could not load graph: {graph_error}")
			elif graph_data:
				render_evidence_graph(graph_data)
			else:
				st.caption("No graph data available for this document.")

			calcs = data.get("calcs", []) or []
			with st.expander("Show my math"):
				if calcs:
					for index, calc in enumerate(calcs):
						label = calc.get("label", "Calculation")
						formula = calc.get("formula", "")
						status = "⚠️" if calc.get("unverifiable", False) else "✅"
						st.markdown(f"**{status} {humanize_formula(label, formula)}**")
						result_value = calc.get("result")
						if result_value is not None:
							st.write(f"Result: {format_currency(result_value)}")
						inputs = calc.get("inputs", [])
						if inputs:
							st.write("Inputs:")
							for input_item in inputs:
								source = input_item.get("source", {})
								page = source.get("page", "?")
								cell = source.get("cell", "?")
								value_display = format_currency(input_item.get("value"))
								st.markdown(
									f"- `{input_item.get('name', '')}` = {value_display} (page {page}, cell {cell})"
								)
						if index < len(calcs) - 1:
							st.divider()
				else:
					st.info("No calculation metadata available for this document.")

			st.write("**Plain-language summary:**")
			st.markdown(data.get("explain_like_12", ""))
			st.write("**Citations:**")
			citations = data.get("citations", []) or []
			st.json(citations)
			audit_hash = data.get("audit_hash")
			if audit_hash:
				st.caption(f"Audit trail: `{audit_hash}`")

			copy_col1, copy_col2 = st.columns(2)
			with copy_col1:
				render_copy_button(
					"Copy explain JSON",
					json.dumps(data, indent=2),
					f"copy-explain-{current_doc_id}",
				)
			with copy_col2:
				render_copy_button(
					"Copy citations",
					json.dumps(citations, indent=2),
					f"copy-citations-{current_doc_id}",
				)

			# Export buttons: DOCX / PDF for the explain payload
			try:
				slug = _slugify(str(current_doc_id))
				export_payload = {
					"doc_id": current_doc_id,
					"persona": persona_value,
					"level": level_value,
					"language": language_value,
				}
				session_for_exports = st.session_state.get("session_id")
				if session_for_exports:
					export_payload["session_id"] = session_for_exports
				payload_json = json.dumps(export_payload)
				api_base_json = json.dumps(api_base)
				filename_doc = json.dumps(f"LumiClaim_Explain_{current_doc_id}.docx")
				filename_pdf = json.dumps(f"LumiClaim_Explain_{current_doc_id}.pdf")
				st_components.html(
					f"""
						<div style='display:flex;flex-wrap:wrap;gap:10px;margin-top:8px;'>
							<button id='export-explain-docx-{slug}' style='padding:8px 12px;border-radius:6px;border:1px solid #1d4ed8;background-color:#2563eb;color:#f8fafc;font-size:0.9rem;cursor:pointer;'>Export Explain (.docx)</button>
							<button id='export-explain-pdf-{slug}' style='padding:8px 12px;border-radius:6px;border:1px solid #047857;background-color:#059669;color:#f8fafc;font-size:0.9rem;cursor:pointer;'>Export Explain (.pdf)</button>
						</div>
						<script>
						(function() {{
							const payload = {payload_json};
							const baseUrl = {api_base_json};
							const docxBtn = document.getElementById('export-explain-docx-{slug}');
							const pdfBtn = document.getElementById('export-explain-pdf-{slug}');
							const cleanBase = baseUrl.endsWith('/') ? baseUrl.slice(0, -1) : baseUrl;
							async function trigger(endpoint, filename) {{
								try {{
									const response = await fetch(cleanBase + endpoint, {{
										method: 'POST',
										headers: {{ 'Content-Type': 'application/json' }},
										body: JSON.stringify(payload),
									}});
									if (!response.ok) {{
										const msg = await response.text();
										alert('Export failed: ' + (msg || response.status));
										return;
									}}
									const blob = await response.blob();
									const url = window.URL.createObjectURL(blob);
									const link = document.createElement('a');
									link.href = url;
									link.download = filename;
									document.body.appendChild(link);
									link.click();
									link.remove();
									setTimeout(() => window.URL.revokeObjectURL(url), 500);
								}} catch (err) {{
								alert('Unable to export file.');
							}}
							}}
							if (docxBtn) docxBtn.addEventListener('click', () => trigger('/export/explain_docx', {filename_doc}));
							if (pdfBtn) pdfBtn.addEventListener('click', () => trigger('/export/explain_pdf', {filename_pdf}));
						}})();
						</script>
					""",
					height=90,
				)
			except Exception:
				# non-fatal: skip adding export UI when something goes wrong
				pass

			with st.expander("Copy JSON / Debug", expanded=False):
				st.json(data)
				st.download_button(
					"Download JSON",
					data=json.dumps(data, indent=2),
					file_name=f"{current_doc_id}_explain.json",
					mime="application/json",
				)

	st.divider()
	st.header("🎚️ Simulate")
	# default simulation doc uses favorite or most recent upload unless user selects another
	active_doc_for_sim = st.session_state.get("active_doc_id")
	sim_default = active_doc_for_sim or st.session_state.get("favorite_doc_id") or (
		(st.session_state.get("last_upload") or {}).get("doc_id") if isinstance(st.session_state.get("last_upload"), dict) else None
	) or st.session_state.get("current_doc_id", "EOB-001")

	sim_doc_id = st.text_input("Simulation Document ID", value=sim_default or current_doc_id, key="sim_doc_id")

	# Option to use stored plan profile
	use_plan_profile = st.checkbox("Use plan profile", value=False, key="use_plan_profile")
	profile_session_to_use = st.session_state.get("profile_session_id") or st.session_state.get("profile_session_id_input")
	if use_plan_profile and profile_session_to_use:
		prof_resp, prof_err = request_json("GET", f"{api_base}/profile/get", params={"session_id": profile_session_to_use})
		if prof_err:
			st.error(f"Unable to load profile: {prof_err}")
			use_plan_profile = False
		else:
			prof = prof_resp.get("profile") if isinstance(prof_resp, dict) else None
			if prof:
				# populate session defaults for simulation inputs
				st.session_state["deductible_remaining_input"] = prof.get("deductible_remaining") or st.session_state.get("deductible_remaining_input", 0.0)
				st.session_state["coinsurance_input"] = prof.get("coinsurance") or st.session_state.get("coinsurance_input", 0.2)
				st.session_state["oop_remaining_input"] = prof.get("oop_remaining") or st.session_state.get("oop_remaining_input", 0.0)

	preset_col, _, inputs_col = st.columns([1.5, 0.2, 2])

	PRESETS = {
		"Custom": None,
		"High deductible": {
			"deductible_remaining": 2500.0,
			"coinsurance": 0.3,
			"oop_remaining": 4800.0,
		},
		"Low deductible": {
			"deductible_remaining": 200.0,
			"coinsurance": 0.1,
			"oop_remaining": 1200.0,
		},
		"Max OOP nearly reached": {
			"deductible_remaining": 50.0,
			"coinsurance": 0.0,
			"oop_remaining": 200.0,
		},
	}

	st.session_state.setdefault("deductible_remaining_input", 500.0)
	st.session_state.setdefault("coinsurance_input", 0.2)
	st.session_state.setdefault("oop_remaining_input", 1500.0)
	st.session_state.setdefault("last_preset", "Custom")

	with preset_col:
		selected_preset = st.radio("Preset", list(PRESETS.keys()), index=0, key="preset_choice")
		preset_values = PRESETS.get(selected_preset)
		if preset_values and st.session_state.get("last_preset") != selected_preset:
			st.session_state["deductible_remaining_input"] = preset_values["deductible_remaining"]
			st.session_state["coinsurance_input"] = preset_values["coinsurance"]
			st.session_state["oop_remaining_input"] = preset_values["oop_remaining"]
		st.session_state["last_preset"] = selected_preset

	with inputs_col:
		deductible_remaining = st.number_input(
			"Deductible remaining" + (" 🔒" if use_plan_profile else ""),
			min_value=0.0,
			value=float(st.session_state["deductible_remaining_input"]),
			step=50.0,
			key="deductible_remaining_input",
			disabled=use_plan_profile,
		)
		coinsurance = st.number_input(
			"Coinsurance" + (" 🔒" if use_plan_profile else ""),
			min_value=0.0,
			max_value=1.0,
			value=float(st.session_state["coinsurance_input"]),
			step=0.05,
			key="coinsurance_input",
			disabled=use_plan_profile,
		)
		oop_remaining = st.number_input(
			"Out-of-pocket remaining" + (" 🔒" if use_plan_profile else ""),
			min_value=0.0,
			value=float(st.session_state["oop_remaining_input"]),
			step=50.0,
			key="oop_remaining_input",
			disabled=use_plan_profile,
		)

	simulation_result = None
	if st.button("Run Simulation", key="simulate_button"):
		payload = {
			"doc_id": sim_doc_id,
			"deductible_remaining": deductible_remaining,
			"coinsurance": coinsurance,
			"oop_remaining": oop_remaining,
		}
		data, error = request_json("POST", f"{api_base}/simulate", json=payload)
		if error:
			st.error(error)
		elif data:
			simulation_result = data
			st.session_state["last_simulation"] = data
			st.session_state["last_simulation_doc"] = sim_doc_id
	elif st.session_state.get("last_simulation_doc") == sim_doc_id:
		simulation_result = st.session_state.get("last_simulation")

	if simulation_result:
		expected_patient = float(simulation_result.get("expected_patient_resp", 0.0))
		delta_vs_bill = float(simulation_result.get("delta_vs_bill", 0.0))
		billed = expected_patient - delta_vs_bill
		details_obj = simulation_result.get("details")
		fair_value = details_obj.get("fair_bill") if isinstance(details_obj, dict) else None
		try:
			fair_bill = float(fair_value) if fair_value is not None else expected_patient
		except (TypeError, ValueError):
			fair_bill = expected_patient

		comparison_rows = [
			("Current bill", billed),
			("Policy simulation", expected_patient),
			("Fair bill (PSL)", float(fair_bill)),
		]

		rows_html = "".join(
			f"<tr><td style='padding:6px;color:#0f172a;font-weight:600;'>{label}</td>"
			f"<td style='padding:6px;text-align:right;font-variant-numeric:tabular-nums;color:#0f172a;'>${amount:,.2f}</td></tr>"
			for label, amount in comparison_rows
		)
		comparison_table = (
			"<table style='width:100%;border-collapse:collapse;margin-top:0.75rem;'>"
			"<thead><tr><th style='text-align:left;padding:6px;color:#0f172a;'>Scenario</th>"
			"<th style='text-align:right;padding:6px;color:#0f172a;'>Amount</th></tr></thead>"
			f"<tbody>{rows_html}</tbody></table>"
		)
		st.markdown(comparison_table, unsafe_allow_html=True)
		st.write(f"**Expected to owe:** ${expected_patient:,.2f}")
		st.write(f"**Delta vs bill:** ${delta_vs_bill:,.2f}")
		st.write("**Details:**")
		st.json(simulation_result.get("details", {}))
		st.write("**Citations:**")
		st.json(simulation_result.get("citations", []))


with actions_tab:
	current_doc = st.session_state.get("current_doc_id", "EOB-001")
	st.subheader("Upload & Redact")
	uploaded_text = st.text_area(
		"Paste claim text to redact",
		value=st.session_state.get("redacted_preview", ""),
		height=200,
		key="redaction_input",
	)
	redact_cols = st.columns([1, 1])
	if redact_cols[0].button("Redact & Store", key="redact_button"):
		payload = {"doc_id": current_doc, "content": uploaded_text}
		response, error = request_json("POST", f"{api_base}/upload", json=payload)
		if error:
			st.error(error)
		elif response:
			st.session_state["privacy_redacted_doc"] = response.get("doc_id")
			st.session_state["last_upload"] = response
			st.session_state["redacted_preview"] = response.get("content", "")
			st.success("Uploaded and redacted successfully.")
			st.caption(f"Audit trail: `{response.get('audit_hash', '')}`")
	if st.session_state.get("redacted_preview"):
		st.text_area(
			"Redacted preview",
			value=st.session_state["redacted_preview"],
			height=200,
			key="redaction_preview",
			disabled=True,
		)
	st.divider()
	st.header("⚖️ Compare")
	compare_a = st.text_input("Document A", value="EOB-001", key="compare_a")
	compare_b = st.text_input("Document B", value="EOB-002", key="compare_b")
	if st.button("Compare", key="compare_button"):
		params = {"a": compare_a, "b": compare_b}
		data, error = request_json("GET", f"{api_base}/compare", params=params)
		if error:
			st.error(error)
		elif data:
			st.write("**Diff:**")
			st.json(data.get("diff", []))
			st.write("**Citations:**")
			st.json(data.get("citations", []))

	st.divider()
	st.header("📨 Appeal")
	st.caption(f"Current document: {current_doc}")
	appeal_tone = st.selectbox("Tone", ["polite", "firm"], index=0, key="appeal_tone")
	appeal_audience = st.selectbox("Audience", ["payer", "provider"], index=0, key="appeal_audience")

	if st.button("Generate Appeal", key="appeal_button"):
		if not current_doc:
			st.error("Set a document ID in the Review tab before generating an appeal.")
		else:
			payload = {"doc_id": current_doc, "tone": appeal_tone, "audience": appeal_audience}
			data, error = request_json("POST", f"{api_base}/appeal", json=payload)
			if error:
				st.error(error)
			elif data:
				# persist latest appeal payload for audit / UI
				st.session_state["appeal_data"] = data
				st.write(f"**Subject:** {data.get('subject', '')}")
				st.write("**Body:**")
				st.write(data.get("body", ""))
				audit_hash = data.get("audit_hash")
				if audit_hash:
					st.caption(f"Audit trail: `{audit_hash}`")
				psl_delta_value = data.get("psl_delta")
				if psl_delta_value is not None:
					try:
						delta_display = f"${float(psl_delta_value):,.2f}"
					except (TypeError, ValueError):
						delta_display = str(psl_delta_value)
					st.write(f"**Policy Simulation Delta:** {delta_display}")
				st.write("**Exhibits:**")
				exhibits = data.get("exhibits", [])
				for exhibit in exhibits:
					st.markdown(
						f"- **{exhibit.get('label', '')}** — {exhibit.get('title', '')}"
					)
				proof_pack = data.get("proof_pack") or {}
				if proof_pack:
					with st.expander("Proof Pack Overview"):
						st.write("**Exhibit index:**")
						st.json(proof_pack.get("exhibit_index", []))
					st.download_button(
						"Download Proof Pack (.json)",
						data=json.dumps(proof_pack, indent=2),
						file_name=f"{current_doc}_proof_pack.json",
						mime="application/json",
					)
				appeal_content = (
					f"Subject: {data.get('subject', '')}\n\n"
					f"{data.get('body', '')}\n\n"
					"Exhibits:\n"
					+ "\n".join(
						f"{exhibit.get('label', '')}: {exhibit.get('title', '')}"
						for exhibit in exhibits
					)
				)
				st.download_button(
					"Download as .txt",
					data=appeal_content,
					file_name=f"{current_doc}_appeal.txt",
					mime="text/plain",
				)
				download_payload = dict(payload)
				psl_delta_value = data.get("psl_delta")
				if psl_delta_value is not None:
					download_payload["psl_delta"] = psl_delta_value
				slug = _slugify(str(download_payload.get("doc_id", "appeal")))
				session_for_downloads = st.session_state.get("session_id")
				if session_for_downloads:
					download_payload.setdefault("session_id", session_for_downloads)
				payload_json = json.dumps(download_payload)
				api_base_json = json.dumps(api_base)
				filename_doc = json.dumps(f"LumiClaim_Appeal_{download_payload.get('doc_id', 'appeal')}.docx")
				filename_pdf = json.dumps(f"LumiClaim_Appeal_{download_payload.get('doc_id', 'appeal')}.pdf")
				st_components.html(
					f"""
						<div style='display:flex;flex-wrap:wrap;gap:10px;margin-top:12px;'>
							<button id='download-docx-{slug}' style='padding:8px 14px;border-radius:6px;border:1px solid #1d4ed8;background-color:#2563eb;color:#f8fafc;font-size:0.9rem;cursor:pointer;'>Download as Word (.docx)</button>
							<button id='download-pdf-{slug}' style='padding:8px 14px;border-radius:6px;border:1px solid #047857;background-color:#059669;color:#f8fafc;font-size:0.9rem;cursor:pointer;'>Download as PDF (.pdf)</button>
						</div>
						<script>
						(function() {{
							const payload = {payload_json};
							const baseUrl = {api_base_json};
							const docxBtn = document.getElementById('download-docx-{slug}');
							const pdfBtn = document.getElementById('download-pdf-{slug}');
							const cleanBase = baseUrl.endsWith('/') ? baseUrl.slice(0, -1) : baseUrl;
							async function triggerDownload(ext) {{
								try {{
									const endpoint = cleanBase + '/appeal_' + ext;
									const response = await fetch(endpoint, {{
										method: 'POST',
										headers: {{ 'Content-Type': 'application/json' }},
										body: JSON.stringify(payload),
									}});
									if (!response.ok) {{
										const message = await response.text();
										alert('Download failed (' + ext.toUpperCase() + '): ' + (message || response.status));
										return;
									}}
									const blob = await response.blob();
									const url = window.URL.createObjectURL(blob);
									const link = document.createElement('a');
									link.href = url;
									link.download = ext === 'docx' ? {filename_doc} : {filename_pdf};
									document.body.appendChild(link);
									link.click();
									link.remove();
									setTimeout(() => window.URL.revokeObjectURL(url), 500);
								}} catch (error) {{
									alert('Unable to download appeal (' + ext.toUpperCase() + ').');
								}}
							}}
							if (docxBtn) {{
								docxBtn.addEventListener('click', () => triggerDownload('docx'));
							}}
							if (pdfBtn) {{
								pdfBtn.addEventListener('click', () => triggerDownload('pdf'));
							}}
						}})();
						</script>
					""",
					height=110,
				)
				st.divider()
