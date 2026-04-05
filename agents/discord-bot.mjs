/**
 * Discord Bot — Cheafi Trading Team
 * Clean, aligned embeds with consistent structure.
 */
import { Client, GatewayIntentBits, EmbedBuilder } from "discord.js";
import pino from "pino";

const log = pino({
  level: process.env.LOG_LEVEL || "info",
  transport: process.env.NODE_ENV !== "production" ? { target: "pino-pretty" } : undefined,
});

const DISCORD_TOKEN = process.env.DISCORD_BOT_TOKEN || "";
const CHANNEL_NAME = process.env.DISCORD_CHANNEL_NAME || "Trading CC";
const API_BASE = "http://localhost:3001";
let client = null;
let tradingChannel = null;
let digestInterval = null;

const API_KEY = process.env.ML_TRAIN_API_KEY || "";

// === Helpers ===
async function api(path) {
  try { const r = await fetch(`${API_BASE}${path}`); return r.ok ? r.json() : null; }
  catch { return null; }
}
async function apiPost(path, body = {}) {
  try {
    const headers = { "Content-Type": "application/json" };
    if (API_KEY) headers["X-API-Key"] = API_KEY;
    const r = await fetch(`${API_BASE}${path}`, {
      method: "POST", headers,
      body: JSON.stringify(body),
    });
    return r.json();
  } catch { return null; }
}

function pct(v, d = 1) { return v != null && !isNaN(v) ? `${Number(v).toFixed(d)}%` : "\u2014"; }
function coin(v, d = 2) { const n = Number(v) || 0; return `${n >= 0 ? "+" : ""}${n.toFixed(d)}`; }
function num(v, d = 2) { return v != null && !isNaN(v) ? Number(v).toFixed(d) : "\u2014"; }
function pad(s, w, a = "r") { const t = String(s); return t.length >= w ? t.slice(0, w) : a === "r" ? t.padStart(w) : t.padEnd(w); }
function riskEmoji(l) { return { CRITICAL: "\ud83d\udd34", HIGH: "\ud83d\udfe0", MEDIUM: "\ud83d\udfe1", LOW: "\ud83d\udfe2" }[l] || "\u26aa"; }
function timeAgo(iso) { return iso ? `<t:${Math.floor(new Date(iso).getTime() / 1000)}:R>` : "\u2014"; }

function getDDPct(p) { const raw = p?.max_drawdown ?? 0; return Math.min(raw > 1 ? raw : raw * 100, 100); }
function getWR(p) {
  if (p?.winrate != null) return (p.winrate * 100).toFixed(1);
  const t = p?.trade_count ?? 0, w = p?.winning_trades ?? 0;
  return t > 0 ? ((w / t) * 100).toFixed(1) : "\u2014";
}
function getPF(p) { return p?.profit_factor != null ? Number(p.profit_factor).toFixed(2) : "\u2014"; }

// === Events ===
async function onReady() {
  log.info(`\ud83e\udd16 Discord READY: ${client.user.tag}`);
  const chs = client.channels.cache.filter(c => c.isTextBased());
  const norm = CHANNEL_NAME.toLowerCase().replace(/\s+/g, "-");
  const match = chs.filter(c => c.name === CHANNEL_NAME || c.name === norm || c.name.toLowerCase().includes(norm));
  tradingChannel = match.size > 0 ? match.first() : chs.first() || null;
  if (tradingChannel) { log.info(`\ud83d\udce2 #${tradingChannel.name}`); await sendOnlineEmbed(); }
  startDigest();
}

async function onMessage(message) {
  if (message.author.bot) return;
  if (!tradingChannel && message.channel.name) {
    const n = CHANNEL_NAME.toLowerCase().replace(/\s+/g, "-");
    if (message.channel.name === n || message.channel.name === CHANNEL_NAME) tradingChannel = message.channel;
  }
  const cmd = message.content.trim().toLowerCase().split(/\s+/)[0];
  const map = {
    "!help": cmdHelp, "!dashboard": cmdDashboard, "!dash": cmdDashboard,
    "!pnl": cmdPnL, "!profit": cmdPnL, "!risk": cmdRisk, "!ml": cmdML,
    "!agents": cmdAgents, "!status": cmdAgents, "!strategies": cmdStrategies, "!strats": cmdStrategies,
    "!findings": cmdFindings, "!trades": cmdTrades, "!pairs": cmdPairs, "!pair": cmdPairs,
    "!summary": cmdSummary, "!sum": cmdSummary, "!config": cmdConfig, "!cfg": cmdConfig,
    "!backtest": cmdBacktest, "!train": cmdTrain, "!results": cmdResults,
    "!health": cmdHealth, "!digest": cmdDigest,
  };
  try { if (map[cmd]) await map[cmd](message); }
  catch (e) { log.error({ err: e, cmd }, "Cmd error"); await message.reply(`\u274c ${e.message}`).catch(() => {}); }
}

// === Init ===
export async function initDiscord() {
  log.info("\ud83d\udd0c Init Discord...");
  if (!DISCORD_TOKEN) { log.error("\u274c No token"); return false; }
  client = new Client({ intents: [GatewayIntentBits.Guilds, GatewayIntentBits.GuildMessages, GatewayIntentBits.MessageContent] });
  client.on("clientReady", onReady);
  client.on("error", e => log.error({ err: e }, "Discord err"));
  client.on("messageCreate", onMessage);
  try { await client.login(DISCORD_TOKEN); return true; }
  catch (err) {
    if (err.message?.includes("disallowed intents")) {
      log.warn("\u26a0\ufe0f Retry without MessageContent...");
      client.destroy();
      client = new Client({ intents: [GatewayIntentBits.Guilds, GatewayIntentBits.GuildMessages] });
      client.on("clientReady", onReady); client.on("error", e => log.error({ err: e })); client.on("messageCreate", onMessage);
      try { await client.login(DISCORD_TOKEN); return true; } catch { client = null; return false; }
    }
    log.error({ err }, "Login failed"); client = null; return false;
  }
}

// === Online ===
async function sendOnlineEmbed() {
  if (!tradingChannel) return;
  const h = await api("/health");
  const embed = new EmbedBuilder().setColor(0x00ff88)
    .setTitle("\ud83d\ude80 Cheafi \u2014 Online")
    .setDescription(["```yml",`Status : Operational`,`Agents : ${h?.agents||0} active`,`Web    : http://localhost:3000`,`API    : http://localhost:3001`,"```"].join("\n"))
    .addFields(
      { name: "\ud83d\udcca Monitor", value: "`!dash` `!pnl` `!summary`", inline: true },
      { name: "\ud83e\udde0 Intel",   value: "`!ml` `!agents` `!strats`",  inline: true },
      { name: "\u26a1 Actions",  value: "`!backtest` `!train` `!help`",inline: true },
    )
    .setFooter({ text: "Cheafi \ud83d\udc3c \u2022 Digest every 4h" }).setTimestamp();
  await tradingChannel.send({ embeds: [embed] }).catch(() => {});
}

// === COMMANDS ===

async function cmdHelp(msg) {
  const e = new EmbedBuilder().setColor(0x5865f2).setTitle("\ud83d\udcd6 Commands")
    .addFields(
      { name: "\ud83d\udcca Overview", value: [
        "`!dashboard ` Full overview",
        "`!pnl       ` P&L summary",
        "`!summary   ` Quick stats",
        "`!risk      ` Risk gauge",
        "`!pairs     ` Pair breakdown",
        "`!trades    ` Open positions",
        "`!config    ` Trading config",
      ].join("\n"), inline: false },
      { name: "\ud83e\udde0 Intel", value: [
        "`!ml        ` ML engine",
        "`!agents    ` Team status",
        "`!strategies` Rankings",
        "`!findings  ` Recent reports",
      ].join("\n"), inline: false },
      { name: "\u26a1 Actions", value: [
        "`!backtest [strat] [range]`",
        "`!train    ` ML training",
        "`!results  ` BT results",
        "`!health   ` System check",
        "`!digest   ` Force digest",
      ].join("\n"), inline: false },
    ).setFooter({ text: "Cheafi \ud83d\udc3c" }).setTimestamp();
  await msg.reply({ embeds: [e] });
}

async function cmdDashboard(msg) {
  const [profit, trades, agents, ml] = await Promise.all([api("/api/ft/profit"), api("/api/ft/status"), api("/api/agents"), api("/api/ml/state")]);
  await msg.reply({ embeds: [buildPnL(profit, trades), buildRisk(profit), buildML(ml), buildAgents(agents)] });
}

async function cmdPnL(msg) {
  const [p, t] = await Promise.all([api("/api/ft/profit"), api("/api/ft/status")]);
  await msg.reply({ embeds: [buildPnL(p, t)] });
}

function buildPnL(profit, trades) {
  const total = profit?.profit_all_coin ?? 0;
  const pctVal = profit?.profit_all_percent ?? profit?.profit_all_perc ?? 0;
  const closed = profit?.profit_closed_coin ?? 0;
  const open = Array.isArray(trades) ? trades.length : 0;
  const closedN = profit?.closed_trade_count ?? 0;
  const w = profit?.winning_trades ?? 0, l = profit?.losing_trades ?? 0;
  const pos = total >= 0;

  return new EmbedBuilder().setColor(pos ? 0x00ff88 : 0xff4444)
    .setTitle("\ud83d\udcb0 P&L Overview")
    .setDescription(["```diff",`${pos?"+":""}${total.toFixed(2)} USDT  (${pos?"+":""}${pctVal.toFixed(2)}%)`,"```"].join("\n"))
    .addFields(
      { name: "Closed",        value: `\`${coin(closed)} USDT\``,  inline: true },
      { name: "Win Rate",      value: `\`${getWR(profit)}%\``,     inline: true },
      { name: "Profit Factor", value: `\`${getPF(profit)}\``,      inline: true },
      { name: "Win / Loss",    value: `\u2705 ${w}  \u274c ${l}  \u00b7 ${w+l} trades`, inline: true },
      { name: "Positions",     value: `\ud83d\udcc2 ${open} open \u00b7 \ud83d\udcc1 ${closedN} closed`, inline: true },
    ).setFooter({ text: "Cheafi \ud83d\udc3c" }).setTimestamp();
}

async function cmdRisk(msg) {
  await msg.reply({ embeds: [buildRisk(await api("/api/ft/profit"))] });
}

function buildRisk(profit) {
  const dd = getDDPct(profit);
  const ddAbs = profit?.max_drawdown_abs ?? 0;
  const lv = dd > 20 ? "CRITICAL" : dd > 15 ? "HIGH" : dd > 10 ? "MEDIUM" : "LOW";
  const col = { CRITICAL: 0xff4444, HIGH: 0xffa500, MEDIUM: 0xffcc00, LOW: 0x00ff88 }[lv];
  const bLen = 20, f = Math.round(Math.min(dd / 25, 1) * bLen);
  const bar = "\u2588".repeat(f) + "\u2591".repeat(bLen - f);

  return new EmbedBuilder().setColor(col)
    .setTitle(`\ud83d\udee1\ufe0f Risk \u2014 ${riskEmoji(lv)} ${lv}`)
    .addFields(
      { name: "Max Drawdown", value: ["```",`${bar}  ${dd.toFixed(1)}%`,`0%          15%         25%`,"```"].join("\n"), inline: false },
      { name: "DD Abs",        value: `\`${num(ddAbs)} USDT\``, inline: true },
      { name: "Win Rate",      value: `\`${getWR(profit)}%\``,  inline: true },
      { name: "Profit Factor", value: `\`${getPF(profit)}\``,   inline: true },
      { name: "Sharpe",        value: `\`${num(profit?.sharpe)}\``, inline: true },
      { name: "Sortino",       value: `\`${num(profit?.sortino)}\``,inline: true },
      { name: "Expectancy",    value: `\`${profit?.expectancy!=null ? coin(profit.expectancy,4) : "\u2014"}\``, inline: true },
    ).setFooter({ text: "Cheafi \ud83d\udc3c" }).setTimestamp();
}

async function cmdML(msg) {
  const [ml, hist] = await Promise.all([api("/api/ml/state"), api("/api/ml/history")]);
  await msg.reply({ embeds: [buildML(ml, hist)] });
}

function buildML(ml, history) {
  const regime = ml?.regime || "unknown";
  const rLabel = { TRENDING_UP:"\ud83d\udcc8 Trend \u2191", TRENDING_DOWN:"\ud83d\udcc9 Trend \u2193", RANGING:"\u2194\ufe0f Ranging", VOLATILE:"\u26a1 Volatile", unknown:"\u2753 Unknown" }[regime] || regime;
  const tLabel = { improving:"\u2197\ufe0f Improving", degrading:"\u2198\ufe0f Degrading", stable:"\u2192 Stable" }[ml?.improvementTrend] || "\u2192 Stable";

  const e = new EmbedBuilder().setColor(0x9b59b6).setTitle("\ud83e\udde0 ML Engine")
    .addFields(
      { name: "Regime",   value: `**${rLabel}**`,  inline: true },
      { name: "Strategy", value: `**${ml?.strategy||"\u2014"}**`, inline: true },
      { name: "Trend",    value: `**${tLabel}**`,  inline: true },
      { name: "Win Rate", value: `\`${ml?.winRate ? pct(ml.winRate*100) : "\u2014"}\``, inline: true },
      { name: "Max DD",   value: `\`${ml?.maxDD ? pct(ml.maxDD) : "\u2014"}\``, inline: true },
      { name: "Trained",  value: ml?.lastTrained ? timeAgo(ml.lastTrained) : "Never", inline: true },
    );

  if (ml?.params) {
    const rn = { "0":"Trend \u2191 ", "1":"Trend \u2193 ", "2":"Range   ", "3":"Volatile" };
    const hdr = "Regime    \u2502 Strat \u2502   c  \u2502    e  \u2502   WR  \u2502 Sharpe";
    const sep = "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u253c\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u253c\u2500\u2500\u2500\u2500\u2500\u2500\u253c\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u253c\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u253c\u2500\u2500\u2500\u2500\u2500\u2500\u2500";
    const rows = Object.entries(ml.params).map(([id, p]) => {
      return `${rn[id]||("R"+id+"     ")} \u2502 ${pad(p.strategy||"\u2014",5,"l")} \u2502 ${pad(num(p.c),4)} \u2502 ${pad((p.e>=0?"+":"")+num(p.e),5)} \u2502 ${pad(p.win_rate?pct(p.win_rate*100):"\u2014",5)} \u2502 ${pad(num(p.sharpe),5)}`;
    });
    e.addFields({ name: "\u2699\ufe0f Regime Params", value: `\`\`\`\n${hdr}\n${sep}\n${rows.join("\n")}\n\`\`\``, inline: false });
  }

  if (history?.length > 0) {
    const ch = "\u2581\u2582\u2583\u2584\u2585\u2586\u2587\u2588";
    const sc = history.slice(-20).map(h => { const s = Object.values(h.strategy_scores||{}); return s.reduce((a,x)=>a+(x.score||0),0)/(s.length||1); });
    const mx = Math.max(...sc, 0.01);
    e.addFields({ name: `\ud83d\udcc8 History (${history.length} runs)`, value: `\`${sc.map(s=>ch[Math.min(Math.floor(s/mx*7),7)]).join("")}\``, inline: false });
  }

  return e.setFooter({ text: "Cheafi \ud83d\udc3c" }).setTimestamp();
}

async function cmdAgents(msg) {
  await msg.reply({ embeds: [buildAgents(await api("/api/agents"))] });
}

function buildAgents(agents) {
  if (!agents?.length) return new EmbedBuilder().setColor(0xff4444).setTitle("\ud83e\udd16 Agents").setDescription("\u274c Unavailable").setTimestamp();
  const ic = { idle: "\ud83d\udfe2", running: "\ud83d\udd35", error: "\ud83d\udd34" };
  const lines = agents.map(a => `${a.emoji} **${a.name}**\n${ic[a.status]||"\u26aa"} ${a.status} \u00b7 ${a.findingsCount||0} findings \u00b7 ${a.lastRun ? timeAgo(a.lastRun) : "never"}`);
  return new EmbedBuilder().setColor(0x3498db).setTitle(`\ud83e\udd16 Agents (${agents.length})`).setDescription(lines.join("\n\n")).setFooter({ text: "Cheafi \ud83d\udc3c" }).setTimestamp();
}

async function cmdStrategies(msg) {
  const data = await api("/api/strategies");
  const p = data?.profit;
  const strats = [
    { k:"AdaptiveML", c:0.50, e: 0.00 },
    { k:"A52",        c:0.50, e:-0.18 },
    { k:"OPT",        c:0.65, e: 0.05 },
    { k:"A51",        c:0.35, e: 0.00 },
    { k:"A31",        c:0.80, e:-0.10 },
  ];
  const wr = getWR(p), dd = getDDPct(p).toFixed(1);
  const hdr = " #  Strategy         c      e     WR%    DD%";
  const sep = "\u2500\u2500\u2500 \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500 \u2500\u2500\u2500\u2500\u2500 \u2500\u2500\u2500\u2500\u2500\u2500 \u2500\u2500\u2500\u2500\u2500\u2500 \u2500\u2500\u2500\u2500\u2500\u2500";
  const rows = strats.map((s,i) => {
    const n = s.k.padEnd(15);
    const eStr = (s.e>=0?"+":"")+num(s.e);
    return ` ${i+1}  ${n} ${pad(num(s.c),5)} ${pad(eStr,6)} ${pad(wr,6)} ${pad(dd,6)}`;
  });
  const e = new EmbedBuilder().setColor(0x2ecc71).setTitle("\ud83d\udcca Strategy Ranking")
    .setDescription(`\`\`\`\n${hdr}\n${sep}\n${rows.join("\n")}\n\`\`\``)
    .addFields(
      { name: "Win Rate", value: `\`${wr}%\``, inline: true },
      { name: "Profit Factor", value: `\`${getPF(p)}\``, inline: true },
      { name: "Sharpe", value: `\`${num(p?.sharpe)}\``, inline: true },
    ).setFooter({ text: "Cheafi \ud83d\udc3c" }).setTimestamp();
  await msg.reply({ embeds: [e] });
}

async function cmdFindings(msg) {
  const f = await api("/api/findings?limit=10");
  if (!f?.length) return msg.reply("\ud83d\udced No findings yet.");
  const em = { "quant-researcher":"\ud83d\udd2c", backtester:"\ud83d\udcca", "risk-manager":"\ud83d\udee1\ufe0f", "signal-engineer":"\ud83d\udce1", "market-analyst":"\ud83c\udf0d", "security-auditor":"\ud83d\udd12", "ml-optimizer":"\ud83e\udde0" };
  const lines = f.slice(0,8).map(x => {
    const t = new Date(x.timestamp).toLocaleTimeString("zh-TW",{hour:"2-digit",minute:"2-digit"});
    return `${em[x.agent]||"\ud83e\udd16"} \`${t}\` **${x.agent}**\n> ${x.summary||"\u2014"}`;
  });
  await msg.reply({ embeds: [new EmbedBuilder().setColor(0x3498db).setTitle("\ud83d\udccb Latest Findings").setDescription(lines.join("\n\n")).setFooter({ text: `${Math.min(f.length,8)} shown \u2022 Cheafi \ud83d\udc3c` }).setTimestamp()] });
}

async function cmdTrades(msg) {
  const trades = await api("/api/ft/status");
  if (!trades?.length) {
    return msg.reply({ embeds: [new EmbedBuilder().setColor(0x95a5a6).setTitle("\ud83d\udccb Open Trades")
      .setDescription("```\n\ud83d\ude34 No open positions\n   Waiting for R2 setup...\n```").setFooter({ text: "Cheafi \ud83d\udc3c" }).setTimestamp()] });
  }
  const total = trades.reduce((s,t) => s + (t.profit_abs||0), 0);
  const rows = trades.map(t => {
    const d = t.is_short ? "\ud83d\udd34 SHORT" : "\ud83d\udfe2 LONG ";
    const p = (t.pair||"?").replace("/USDT:USDT","").padEnd(8);
    return `${d}  ${p}  ${pad(coin(t.profit_pct||0)+"%",8)}  ${t.trade_duration||"\u2014"}`;
  });
  const e = new EmbedBuilder().setColor(0xe67e22).setTitle(`\ud83d\udccb Open Trades (${trades.length})`)
    .setDescription(["```","Dir       Pair      P&L       Duration","\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500  \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500  \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500  \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500",...rows,"\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500  \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500  \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500  \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500",`Total P&L: ${coin(total)} USDT`,"```"].join("\n"))
    .setFooter({ text: "Cheafi \ud83d\udc3c" }).setTimestamp();
  await msg.reply({ embeds: [e] });
}

async function cmdPairs(msg) {
  const perf = await api("/api/ft/performance");
  if (!perf?.length) return msg.reply("\ud83d\udced No pair data yet.");
  const sorted = [...perf].sort((a,b) => (b.profit||0) - (a.profit||0));
  const rows = sorted.map(p => {
    const ic = (p.profit||0) > 0 ? "\ud83d\udfe2" : (p.profit||0) < 0 ? "\ud83d\udd34" : "\u26aa";
    const nm = (p.pair||"\u2014").replace("/USDT:USDT","").replace("/USDT","").padEnd(10);
    return `${ic} ${nm}  ${pad(p.count||0,4)}   ${pad(coin(p.profit||0),7)}%`;
  });
  const tp = sorted.reduce((s,p)=>s+(p.profit||0),0);
  const tt = sorted.reduce((s,p)=>s+(p.count||0),0);
  const e = new EmbedBuilder().setColor(tp>=0?0x00ff88:0xff4444)
    .setTitle(`\ud83c\udfc6 Pair Performance (${sorted.length})`)
    .setDescription(["```","   Pair        Trades  Profit","\u2500\u2500 \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500 \u2500\u2500\u2500\u2500\u2500\u2500\u2500 \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500",...rows,"\u2500\u2500 \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500 \u2500\u2500\u2500\u2500\u2500\u2500\u2500 \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500",`   TOTAL       ${pad(tt,4)}   ${pad(coin(tp),7)}%`,"```"].join("\n"))
    .setFooter({ text: "Cheafi \ud83d\udc3c" }).setTimestamp();
  await msg.reply({ embeds: [e] });
}

async function cmdSummary(msg) {
  const [p, t, ml, perf] = await Promise.all([api("/api/ft/profit"), api("/api/ft/status"), api("/api/ml/state"), api("/api/ft/performance")]);
  const total = p?.profit_all_coin??0, pctV = p?.profit_all_percent ?? p?.profit_all_perc ?? 0;
  const wr = getWR(p), pf = getPF(p), dd = getDDPct(p);
  const open = Array.isArray(t) ? t.length : 0;
  const sorted = [...(perf||[])].sort((a,b)=>(b.profit||0)-(a.profit||0));
  const best = sorted[0]?.pair?.replace("/USDT:USDT","").replace("/USDT","")||"\u2014";
  const worst = sorted.at(-1)?.pair?.replace("/USDT:USDT","").replace("/USDT","")||"\u2014";
  const pos = total >= 0;
  const e = new EmbedBuilder().setColor(pos?0x00ff88:0xff4444).setTitle("\u26a1 Quick Summary")
    .setDescription(["```diff",`${pos?"+":""}${total.toFixed(2)} USDT  (${pos?"+":""}${pctV.toFixed(2)}%)`,"```","",
      `\ud83d\udcca **${p?.trade_count??0}** trades \u00b7 \ud83c\udfaf **${wr}%** WR \u00b7 \u2696\ufe0f **${pf}** PF \u00b7 \ud83d\udcc9 **${dd.toFixed(1)}%** DD`,
      `\ud83d\udcc2 **${open}** open \u00b7 \ud83e\udde0 **${ml?.regime||"\u2014"}** \u00b7 \ud83c\udfc6 **${best}** \u00b7 \ud83d\udc80 **${worst}**`
    ].join("\n")).setFooter({ text: "Cheafi \ud83d\udc3c" }).setTimestamp();
  await msg.reply({ embeds: [e] });
}

async function cmdConfig(msg) {
  const [wl, ml] = await Promise.all([api("/api/ft/whitelist"), api("/api/ml/state")]);
  const pairs = (wl?.whitelist||[]).map(p=>p.replace("/USDT:USDT","")).join(", ");
  const e = new EmbedBuilder().setColor(0x5865f2).setTitle("\u2699\ufe0f Config")
    .addFields(
      { name: "Pairs",      value: `\`${pairs||"none"}\` (${wl?.whitelist?.length||0})`, inline: false },
      { name: "Strategy",   value: `\`${ml?.strategy||"\u2014"}\``,  inline: true },
      { name: "Regime",     value: `\`${ml?.regime||"\u2014"}\``,    inline: true },
      { name: "Timeframe",  value: "`5m`",                       inline: true },
      { name: "Max Trades", value: "`4`",                        inline: true },
      { name: "Mode",       value: "`Futures / Isolated`",       inline: true },
      { name: "Direction",  value: "`R2 Short Only`",            inline: true },
    ).setFooter({ text: "Cheafi \ud83d\udc3c" }).setTimestamp();
  await msg.reply({ embeds: [e] });
}

async function cmdBacktest(msg) {
  const parts = msg.content.trim().split(/\s+/);
  const strat = parts[1]||"all", range = parts[2]||"";
  const e = new EmbedBuilder().setColor(0xffa500).setTitle("\u23f3 Backtest Triggered")
    .setDescription(["```yml",`Strategy : ${strat}`,`Range    : ${range||"default (6 months)"}`,`Status   : Running...`,"```","Use `!results` when complete."].join("\n"))
    .setFooter({ text: "Cheafi \ud83d\udc3c" }).setTimestamp();
  await msg.reply({ embeds: [e] });
  apiPost("/api/backtest/run", { strategy: strat, timerange: range }).catch(() => {});
}

async function cmdTrain(msg) {
  await msg.reply({ embeds: [new EmbedBuilder().setColor(0x9b59b6).setTitle("\ud83e\udde0 ML Training Triggered")
    .setDescription("```\nStarting pipeline... Results posted when done.\n```").setFooter({ text: "Cheafi \ud83d\udc3c" }).setTimestamp()] });
  apiPost("/api/ml/train").catch(() => {});
}

async function cmdResults(msg) {
  const res = await api("/api/backtest/results");
  if (!res?.length) return msg.reply("\ud83d\udced No results. Run `!backtest` first.");
  const embeds = res.slice(0,5).map(r => {
    const pos = (r.profit||0) >= 0;
    return new EmbedBuilder().setColor(pos?0x00ff88:0xff4444)
      .setTitle(`${pos?"\ud83d\udcc8":"\ud83d\udcc9"} ${r.strategy}`)
      .addFields(
        { name: "Profit",  value: `\`${pct(r.profit,2)}\``,   inline: true },
        { name: "WR",      value: `\`${pct(r.winRate,1)}\``,  inline: true },
        { name: "DD",      value: `\`${pct(r.maxDrawdown,1)}\``, inline: true },
        { name: "Trades",  value: `\`${r.totalTrades||0}\``,  inline: true },
        { name: "Sharpe",  value: `\`${r.sharpe?.toFixed(2)||"\u2014"}\``, inline: true },
        { name: "Range",   value: `\`${r.timerange||"\u2014"}\``,  inline: true },
      ).setFooter({ text: "Cheafi \ud83d\udc3c" }).setTimestamp(r.timestamp?new Date(r.timestamp):new Date());
  });
  await msg.reply({ embeds });
}

async function cmdHealth(msg) {
  const [h, ds, ft, ag] = await Promise.all([api("/health"), api("/api/discord/status"), api("/api/ft/ping"), api("/api/agents")]);
  const ok1 = h?.ok??false, ok2 = ft!=null, ok3 = ds?.connected??false, errs = (ag||[]).filter(a=>a.status==="error");
  const all = ok1 && ok2 && ok3 && !errs.length;
  const e = new EmbedBuilder().setColor(all?0x00ff88:0xffa500)
    .setTitle(`\ud83d\udd27 Health \u2014 ${all?"\u2705 All OK":"\u26a0\ufe0f Issues"}`)
    .setDescription([
      `${ok1?"\ud83d\udfe2":"\ud83d\udd34"} **Redis** \u2014 ${ok1?"Connected":"Down"}`,
      `${ok2?"\ud83d\udfe2":"\ud83d\udd34"} **Freqtrade** \u2014 ${ok2?"Healthy":"Down"}`,
      `${ok3?"\ud83d\udfe2":"\ud83d\udd34"} **Discord** \u2014 ${ok3?"Connected":"Down"}`,
      `${errs.length?"\ud83d\udfe0":"\ud83d\udfe2"} **Agents** \u2014 ${h?.agents||0} active, ${errs.length} errors`,
    ].join("\n")).setFooter({ text: "Cheafi \ud83d\udc3c" }).setTimestamp();
  await msg.reply({ embeds: [e] });
}

async function cmdDigest(msg) { await msg.reply("\ud83d\udccb Generating..."); await sendDigest(); }

// === Periodic Digest ===
function startDigest() {
  if (digestInterval) clearInterval(digestInterval);
  digestInterval = setInterval(() => sendDigest().catch(()=>{}), 4*3600*1000);
  log.info("\u23f0 4h digest scheduled");
}

async function sendDigest() {
  if (!tradingChannel) return;
  const [p, ag, ml, t, f] = await Promise.all([api("/api/ft/profit"), api("/api/agents"), api("/api/ml/state"), api("/api/ft/status"), api("/api/findings?limit=5")]);
  const total = p?.profit_all_coin??0, pctV = p?.profit_all_percent ?? p?.profit_all_perc ?? 0;
  const dd = getDDPct(p), lv = dd>20?"CRITICAL":dd>15?"HIGH":dd>10?"MEDIUM":"LOW";
  const open = Array.isArray(t)?t.length:0, errs = (ag||[]).filter(a=>a.status==="error");
  const pos = total >= 0;
  const recent = (f||[]).slice(0,3).map(x=>`> ${x.summary||"\u2014"}`).join("\n");

  const e = new EmbedBuilder().setColor(pos?0x00ff88:0xff4444).setTitle("\ud83d\udccb Digest \u2014 Cheafi")
    .setDescription(["```diff",`${pos?"+":""}${total.toFixed(2)} USDT  (${pos?"+":""}${pctV.toFixed(2)}%)`,"```"].join("\n"))
    .addFields(
      { name: "Risk",     value: `${riskEmoji(lv)} ${lv} \u00b7 DD ${dd.toFixed(1)}%`, inline: true },
      { name: "Open",     value: `${open} positions`,  inline: true },
      { name: "Win Rate", value: `${getWR(p)}%`,       inline: true },
      { name: "Regime",   value: `${ml?.regime||"\u2014"} \u2192 ${ml?.strategy||"\u2014"}`, inline: true },
      { name: "PF",       value: getPF(p),              inline: true },
      { name: "Agents",   value: `${ag?.length||0} ok \u00b7 ${errs.length} err`, inline: true },
    );
  if (recent) e.addFields({ name: "Recent", value: recent, inline: false });
  e.setFooter({ text: "Auto \u00b7 Next 4h \u00b7 !digest to force" }).setTimestamp();
  await tradingChannel.send({ embeds: [e] });
  log.info("\ud83d\udccb Digest sent");
}

// === Notifications (called by coordinator) ===
export async function sendBacktestResult(r) {
  if (!tradingChannel) return;
  const pos = (r.profit||0)>=0;
  const e = new EmbedBuilder().setColor(pos?0x00ff88:0xff4444)
    .setTitle(`${pos?"\ud83d\udcc8":"\ud83d\udcc9"} Backtest: ${r.strategy}`)
    .addFields(
      { name: "Profit",value:`\`${pct(r.profit,2)}\``,inline:true },
      { name: "WR",    value:`\`${pct(r.winRate,1)}\``,inline:true },
      { name: "DD",    value:`\`${pct(r.maxDrawdown,1)}\``,inline:true },
      { name: "Trades",value:`\`${r.totalTrades||0}\``,inline:true },
      { name: "Sharpe",value:`\`${r.sharpe?.toFixed(2)||"\u2014"}\``,inline:true },
      { name: "Range", value:`\`${r.timerange||"\u2014"}\``,inline:true },
    ).setFooter({ text: "Cheafi \ud83d\udc3c" }).setTimestamp();
  await tradingChannel.send({ embeds: [e] });
}

export async function sendMLTrainingUpdate(u) {
  if (!tradingChannel) return;
  const e = new EmbedBuilder().setColor(0x9b59b6).setTitle("\ud83e\udde0 ML Training Complete")
    .setDescription(`\`\`\`\n${u.summary||"Done"}\n\`\`\``)
    .addFields(
      { name: "Regime",  value:`\`${u.regime||"\u2014"}\``,  inline:true },
      { name: "Strategy",value:`\`${u.strategy||"\u2014"}\``,inline:true },
      { name: "Trend",   value:`\`${u.trend||"stable"}\``,inline:true },
    ).setFooter({ text: "Cheafi \ud83d\udc3c" }).setTimestamp();
  await tradingChannel.send({ embeds: [e] });
}

export async function sendAlert(level, message) {
  if (!tradingChannel) return;
  const col = { info:0x5865f2, warning:0xffa500, critical:0xff4444, success:0x00ff88 };
  const ico = { info:"\u2139\ufe0f", warning:"\u26a0\ufe0f", critical:"\ud83d\udea8", success:"\u2705" };
  await tradingChannel.send({ embeds: [new EmbedBuilder().setColor(col[level]||0x5865f2)
    .setTitle(`${ico[level]||"\u2139\ufe0f"} ${level.toUpperCase()}`).setDescription(message)
    .setFooter({ text: "Cheafi \ud83d\udc3c" }).setTimestamp()] });
}

export async function sendFinding(finding) {
  if (!tradingChannel) return;
  const em = { "quant-researcher":"\ud83d\udd2c", backtester:"\ud83d\udcca", "risk-manager":"\ud83d\udee1\ufe0f", "signal-engineer":"\ud83d\udce1", "market-analyst":"\ud83c\udf0d", "security-auditor":"\ud83d\udd12", "ml-optimizer":"\ud83e\udde0" };
  const cols = { "risk-assessment":0xffa500, "security-audit":0xff4444, "signal-report":0x2ecc71, "ml-optimization":0x9b59b6 };
  const d = finding.data || {};
  const e = new EmbedBuilder().setColor(cols[finding.type]||0x3498db)
    .setTitle(`${em[finding.agent]||"\ud83e\udd16"} ${finding.agent}`)
    .setDescription(`> ${finding.summary||"Finding"}`);

  if (finding.type === "risk-assessment") {
    e.addFields(
      { name:"Risk",value:`${riskEmoji(d.riskLevel)} ${d.riskLevel||"\u2014"}`,inline:true },
      { name:"DD",  value:pct(d.drawdownPct),inline:true },
      { name:"Open",value:`${d.openTrades??0}`,inline:true },
    );
    if (d.alerts?.length) e.addFields({ name:"\u26a0\ufe0f Alerts",value:d.alerts.join("\n"),inline:false });
  } else if (finding.type === "signal-report" && d.activeSignals?.length) {
    e.addFields({ name:"Signals", value:d.activeSignals.slice(0,5).map(s=>`${s.direction==="SHORT"?"\ud83d\udd34":"\ud83d\udfe2"} **${s.pair}** \`${coin(s.profit)}%\``).join("\n"), inline:false });
  } else if (finding.type === "ml-optimization") {
    e.addFields({ name:"Regime",value:`\`${d.activeRegime||"\u2014"}\``,inline:true },{ name:"Strat",value:`\`${d.activeStrategy||"\u2014"}\``,inline:true },{ name:"WR",value:`\`${pct((d.winRate||0)*100)}\``,inline:true });
  } else if (finding.type === "analysis") {
    e.addFields({ name:"P&L",value:`\`${coin(d.totalProfit)} USDT\``,inline:true },{ name:"Trades",value:`\`${d.tradeCount||0}\``,inline:true },{ name:"Open",value:`\`${d.openTrades||0}\``,inline:true });
  }
  e.setFooter({ text: "Cheafi \ud83d\udc3c" }).setTimestamp();
  await tradingChannel.send({ embeds: [e] });
}

export async function sendRiskAlert(riskData) {
  if (!tradingChannel) return;
  const { riskLevel, drawdownPct, alerts } = riskData;
  if (riskLevel !== "HIGH" && riskLevel !== "CRITICAL") return;
  const e = new EmbedBuilder().setColor(riskLevel==="CRITICAL"?0xff4444:0xffa500)
    .setTitle(`${riskLevel==="CRITICAL"?"\ud83d\udea8":"\u26a0\ufe0f"} RISK \u2014 ${riskLevel}`)
    .setDescription([`**DD: ${pct(drawdownPct)}**`,"",...(alerts||[]),"","\u26a0\ufe0f Immediate attention needed."].join("\n"))
    .setFooter({ text: "Cheafi \ud83d\udc3c \u2022 Risk Manager" }).setTimestamp();
  await tradingChannel.send({ embeds: [e] });
}

export function getStatus() {
  return {
    clientReady: !!client?.isReady(), hasToken: !!DISCORD_TOKEN,
    channelFound: !!tradingChannel, guilds: client?.guilds.cache.size || 0,
    userTag: client?.user?.tag || null, connected: client?.isReady() && !!tradingChannel,
  };
}

export default { initDiscord, sendBacktestResult, sendMLTrainingUpdate, sendAlert, sendFinding, sendRiskAlert, getStatus };
