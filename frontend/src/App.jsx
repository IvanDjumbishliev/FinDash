import { BrowserRouter, Routes, Route, useNavigate } from "react-router-dom";
import Login from "./pages/Login";
import Register from "./pages/Register";
import Home from "./pages/Home";

import NotFound from "./pages/NotFound";
import ProtectedRoute from "./components/ProtectedRoute";

import Footer from "./components/Loyout";

import { lazy, Suspense, useEffect } from "react";
import { clearSession } from "./api";
import { DashboardLoading } from "./components/DashboardWidgets";

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
const Reports = lazy(() => import("./pages/Reports"));
const Notifications = lazy(() => import("./pages/Notifications"));
const NotificationSettings = lazy(() => import("./pages/NotificationSettings"));
const GroceryOptimizer = lazy(() => import("./pages/GroceryOptimizer"));
const CashFlowForecast = lazy(() => import("./pages/CashFlowForecast"));

function PageLoading() {
  return <div className="dashboard-shell"><div className="dash-panel"><DashboardLoading label="Loading page" /></div></div>;
}

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
                <Suspense fallback={<PageLoading />}><Transactions /></Suspense>
              </ProtectedRoute>
            }
          />
          <Route 
            path="/chat"
            element={
              <ProtectedRoute>
                <Suspense fallback={<PageLoading />}><Chat /></Suspense>
              </ProtectedRoute>
            }
          />
          <Route
            path="/promotions"
            element={
              <ProtectedRoute>
                <Suspense fallback={<PageLoading />}><Promotions /></Suspense>
              </ProtectedRoute>
            }
          />
          <Route
            path="/grocery"
            element={<ProtectedRoute><Suspense fallback={<PageLoading />}><GroceryOptimizer /></Suspense></ProtectedRoute>}
          />
          <Route
            path="/stocks"
            element={
              <ProtectedRoute>
                <Suspense fallback={<PageLoading />}><Stocks /></Suspense>
              </ProtectedRoute>
            }
          />
          <Route
            path="/portfolios"
            element={<ProtectedRoute><Suspense fallback={<PageLoading />}><PortfolioSimulator /></Suspense></ProtectedRoute>}
          />
          <Route
            path="/news"
            element={
              <ProtectedRoute>
                <Suspense fallback={<PageLoading />}><News /></Suspense>
              </ProtectedRoute>
            }
          />
          <Route
            path="/budgets"
            element={
              <ProtectedRoute>
                <Suspense fallback={<PageLoading />}><Budgets /></Suspense>
              </ProtectedRoute>
            }
          />
          <Route
            path="/reports"
            element={
              <ProtectedRoute>
                <Suspense fallback={<PageLoading />}><Reports /></Suspense>
              </ProtectedRoute>
            }
          />
          <Route
            path="/forecast"
            element={
              <ProtectedRoute>
                <Suspense fallback={<PageLoading />}><CashFlowForecast /></Suspense>
              </ProtectedRoute>
            }
          />
          <Route path="/goals" element={<ProtectedRoute><Suspense fallback={<PageLoading />}><FinancialGoals /></Suspense></ProtectedRoute>} />
          <Route path="/goals/:id/scenarios" element={<ProtectedRoute><Suspense fallback={<PageLoading />}><GoalScenario /></Suspense></ProtectedRoute>} />
          <Route path="/notifications" element={<ProtectedRoute><Suspense fallback={<PageLoading />}><Notifications /></Suspense></ProtectedRoute>} />
          <Route path="/notifications/settings" element={<ProtectedRoute><Suspense fallback={<PageLoading />}><NotificationSettings /></Suspense></ProtectedRoute>} />
          <Route
            path="/subscriptions"
            element={
              <ProtectedRoute>
                <Suspense fallback={<PageLoading />}><Subscriptions /></Suspense>
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
