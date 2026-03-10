import express from "express";
import { createServer as createViteServer } from "vite";
import cors from "cors";
import crypto from "crypto";
import axios from "axios";
import dotenv from "dotenv";

dotenv.config();

const app = express();
const PORT = 3000;

app.use(cors());
app.use(express.json());

// Binance API Setup
const BINANCE_API_URL = "https://api.binance.com";
const API_KEY = process.env.BINANCE_API_KEY || "";
const API_SECRET = process.env.BINANCE_API_SECRET || "";

const buildSign = (queryString: string) => {
  return crypto.createHmac("sha256", API_SECRET).update(queryString).digest("hex");
};

// --- Binance Endpoints ---

// Get Account Balance (Spot)
app.get("/api/binance/balance", async (req, res) => {
  if (!API_KEY || !API_SECRET) {
    return res.status(400).json({ error: "API keys not configured" });
  }
  try {
    const timestamp = Date.now();
    const queryString = `timestamp=${timestamp}`;
    const signature = buildSign(queryString);

    const response = await axios.get(`${BINANCE_API_URL}/api/v3/account?${queryString}&signature=${signature}`, {
      headers: { "X-MBX-APIKEY": API_KEY },
    });

    // Filter out zero balances
    const balances = response.data.balances.filter((b: any) => parseFloat(b.free) > 0 || parseFloat(b.locked) > 0);
    res.json(balances);
  } catch (error: any) {
    console.error("Binance API Error:", error.response?.data || error.message);
    res.status(500).json({ error: "Failed to fetch balance" });
  }
});

// Get Simple Earn Positions
app.get("/api/binance/earn", async (req, res) => {
  if (!API_KEY || !API_SECRET) {
    return res.status(400).json({ error: "API keys not configured" });
  }
  try {
    const timestamp = Date.now();
    const queryString = `timestamp=${timestamp}`;
    const signature = buildSign(queryString);

    const response = await axios.get(`https://api.binance.com/sapi/v1/simple-earn/flexible/position?${queryString}&signature=${signature}`, {
      headers: { "X-MBX-APIKEY": API_KEY },
    });

    res.json(response.data.rows || []);
  } catch (error: any) {
    console.error("Binance Earn API Error:", error.response?.data || error.message);
    res.status(500).json({ error: "Failed to fetch earn positions" });
  }
});

// Get Funding Rates (Public)
app.get("/api/binance/funding", async (req, res) => {
  try {
    const response = await axios.get("https://fapi.binance.com/fapi/v1/premiumIndex");
    // Sort by absolute funding rate descending
    const rates = response.data
      .filter((r: any) => r.lastFundingRate)
      .sort((a: any, b: any) => Math.abs(parseFloat(b.lastFundingRate)) - Math.abs(parseFloat(a.lastFundingRate)))
      .slice(0, 10); // Top 10 extremes
    res.json(rates);
  } catch (error: any) {
    console.error("Binance Funding API Error:", error.response?.data || error.message);
    res.status(500).json({ error: "Failed to fetch funding rates" });
  }
});

// Get Top Movers (Public)
app.get("/api/binance/ticker/24hr", async (req, res) => {
  try {
    const response = await axios.get(`${BINANCE_API_URL}/api/v3/ticker/24hr`);
    const usdtPairs = response.data.filter((t: any) => t.symbol.endsWith("USDT"));
    
    const topGainers = [...usdtPairs].sort((a: any, b: any) => parseFloat(b.priceChangePercent) - parseFloat(a.priceChangePercent)).slice(0, 5);
    const topLosers = [...usdtPairs].sort((a: any, b: any) => parseFloat(a.priceChangePercent) - parseFloat(b.priceChangePercent)).slice(0, 5);
    
    res.json({ topGainers, topLosers });
  } catch (error: any) {
    console.error("Binance Ticker API Error:", error.response?.data || error.message);
    res.status(500).json({ error: "Failed to fetch tickers" });
  }
});

const CATEGORIES = {
  "Inteligência Artificial (IA)": ["FETUSDT", "AGIXUSDT", "RNDRUSDT", "OCEANUSDT", "TAOUSDT", "WLDUSDT", "NEARUSDT"],
  "Memecoins": ["DOGEUSDT", "SHIBUSDT", "PEPEUSDT", "WIFUSDT", "BONKUSDT", "FLOKIUSDT"],
  "Layer 1 / Infra": ["BTCUSDT", "ETHUSDT", "SOLUSDT", "AVAXUSDT", "ADAUSDT", "SUIUSDT", "APTUSDT"],
  "DeFi": ["UNIUSDT", "AAVEUSDT", "MKRUSDT", "CRVUSDT", "LDOUSDT", "LINKUSDT"]
};

// Get Narratives
app.get("/api/binance/narratives", async (req, res) => {
  try {
    const response = await axios.get(`${BINANCE_API_URL}/api/v3/ticker/24hr`);
    const tickers = response.data;
    
    const narrativeStats = Object.entries(CATEGORIES).map(([name, symbols]) => {
      const categoryTickers = tickers.filter((t: any) => symbols.includes(t.symbol));
      if (categoryTickers.length === 0) return null;
      
      const avgChange = categoryTickers.reduce((sum: number, t: any) => sum + parseFloat(t.priceChangePercent), 0) / categoryTickers.length;
      const totalVolume = categoryTickers.reduce((sum: number, t: any) => sum + parseFloat(t.quoteVolume), 0);
      const topCoin = categoryTickers.sort((a: any, b: any) => parseFloat(b.priceChangePercent) - parseFloat(a.priceChangePercent))[0];
      
      return {
        name,
        avgChange: avgChange.toFixed(2),
        totalVolume,
        topCoin: {
          symbol: topCoin.symbol.replace('USDT', ''),
          change: parseFloat(topCoin.priceChangePercent).toFixed(2)
        }
      };
    }).filter(Boolean);
    
    // Sort by highest average change
    narrativeStats.sort((a: any, b: any) => parseFloat(b.avgChange) - parseFloat(a.avgChange));
    
    res.json(narrativeStats);
  } catch (error: any) {
    console.error("Binance Narratives API Error:", error.response?.data || error.message);
    res.status(500).json({ error: "Failed to fetch narratives" });
  }
});

// Vite middleware for development
async function startServer() {
  if (process.env.NODE_ENV !== "production") {
    const vite = await createViteServer({
      server: { middlewareMode: true },
      appType: "spa",
    });
    app.use(vite.middlewares);
  } else {
    app.use(express.static("dist"));
  }

  app.listen(PORT, "0.0.0.0", () => {
    console.log(`Server running on http://localhost:${PORT}`);
  });
}

startServer();
