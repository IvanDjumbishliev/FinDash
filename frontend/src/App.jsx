import { BrowserRouter, Routes, Route, useNavigate } from "react-router-dom";
import Login from "./pages/Login";
import Register from "./pages/Register";
import Home from "./pages/Home";

import NotFound from "./pages/NotFound";
import ProtectedRoute from "./components/ProtectedRoute";

import Footer from "./components/Loyout";

import { lazy, useEffect } from "react";
import { clearSession } from "./api";

const Chat = lazy(() => import("./pages/Chat"));
const Transactions = lazy(() => import("./pages/Transactions"));
const Promotions = lazy(() => import("./pages/Promotions"));
const Stocks = lazy(() => import("./pages/Stocks"));
const PortfolioSimulator = lazy(() => import("./pages/PortfolioSimulator"));
const News = lazy(() => import("./pages/News"));
const Subscriptions = lazy(() => import("./pages/Subscriptions"));
const Budgets = lazy(() => import("./pages/Budgets"));
const FinancialGoals = lazy(() => import("./pages/FinancialGoals"));
const GoalScenario = lazy(() => import("./pages/GoalScenario"));
const ReceiptHistory = lazy(() => import("./pages/ReceiptHistory"));
const Receipts = lazy(() => import("./pages/Receipts"));
const Reports = lazy(() => import("./pages/Reports"));
const Notifications = lazy(() => import("./pages/Notifications"));
const NotificationSettings = lazy(() => import("./pages/NotificationSettings"));
const MyProducts = lazy(() => import("./pages/MyProducts"));
const GroceryOptimizer = lazy(() => import("./pages/GroceryOptimizer"));
const CashFlowForecast = lazy(() => import("./pages/CashFlowForecast"));

function Logout() {
  const navigate = useNavigate();
  useEffect(() => {
    clearSession();
    navigate("/login", { replace: true });
  }, [navigate]);
  return null;
}

function RegisterAndLogout() {
  useEffect(() => { clearSession(); }, []);
  return <Register />;
}

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Footer/>}>
          <Route
            path="/"
            element={
              <ProtectedRoute>
                <Home />
              </ProtectedRoute>
            }
          />
          <Route
            path="/transactions"
            element={
              <ProtectedRoute>
                <Transactions />
              </ProtectedRoute>
            }
          />
          <Route 
            path="/chat"
            element={
              <ProtectedRoute>
                <Chat />
              </ProtectedRoute>
            }
          />
          <Route
            path="/promotions"
            element={
              <ProtectedRoute>
                <Promotions />
              </ProtectedRoute>
            }
          />
          <Route
            path="/grocery"
            element={<ProtectedRoute><GroceryOptimizer /></ProtectedRoute>}
          />
          <Route
            path="/stocks"
            element={
              <ProtectedRoute>
                <Stocks />
              </ProtectedRoute>
            }
          />
          <Route
            path="/portfolios"
            element={<ProtectedRoute><PortfolioSimulator /></ProtectedRoute>}
          />
          <Route
            path="/news"
            element={
              <ProtectedRoute>
                <News />
              </ProtectedRoute>
            }
          />
          <Route
            path="/budgets"
            element={
              <ProtectedRoute>
                <Budgets />
              </ProtectedRoute>
            }
          />
          <Route
            path="/reports"
            element={
              <ProtectedRoute>
                <Reports />
              </ProtectedRoute>
            }
          />
          <Route
            path="/forecast"
            element={
              <ProtectedRoute>
                <CashFlowForecast />
              </ProtectedRoute>
            }
          />
          <Route path="/my-products" element={<ProtectedRoute><MyProducts /></ProtectedRoute>} />
          <Route path="/receipts" element={<ProtectedRoute><Receipts /></ProtectedRoute>} />
          <Route path="/receipts/history" element={<ProtectedRoute><ReceiptHistory /></ProtectedRoute>} />
          <Route path="/goals" element={<ProtectedRoute><FinancialGoals /></ProtectedRoute>} />
          <Route path="/goals/:id/scenarios" element={<ProtectedRoute><GoalScenario /></ProtectedRoute>} />
          <Route path="/notifications" element={<ProtectedRoute><Notifications /></ProtectedRoute>} />
          <Route path="/notifications/settings" element={<ProtectedRoute><NotificationSettings /></ProtectedRoute>} />
          <Route
            path="/subscriptions"
            element={
              <ProtectedRoute>
                <Subscriptions />
              </ProtectedRoute>
            }
          />
        </Route>
        <Route path="/register" element={<RegisterAndLogout />} />
        <Route path="/login" element={<Login />} />
        <Route path="/logout" element={<Logout />} />
        
        <Route path="*" element={<NotFound />}></Route>
      </Routes>
    </BrowserRouter>
  );
}

export default App;
