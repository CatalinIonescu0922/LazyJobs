import { useQuery } from "@tanstack/react-query";
import { createBrowserRouter, Navigate, Outlet } from "react-router-dom";
import { meQuery } from "./api";
import Home from "./pages/Home";
import SignIn from "./pages/SignIn";

function ProtectedRoute() {
  const me = useQuery(meQuery);
  if (me.isPending) {
    return <p className="p-6 text-slate-500">Loading...</p>;
  }
  if (me.isError) {
    return <Navigate to="/sign-in" replace />;
  }
  return <Outlet />;
}

export const router = createBrowserRouter([
  { path: "/sign-in", element: <SignIn /> },
  {
    element: <ProtectedRoute />,
    children: [{ path: "/", element: <Home /> }],
  },
]);
