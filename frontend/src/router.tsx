import { useQuery } from "@tanstack/react-query";
import { createBrowserRouter, Navigate, Outlet, useLocation } from "react-router-dom";
import { meQuery, profileQuery } from "./api";
import Home from "./pages/Home";
import SignIn from "./pages/SignIn";
import Profile from "./pages/Profile";
import Sources from "./pages/Sources";

function ProtectedRoute() {
  const me = useQuery(meQuery);
  const profile = useQuery({ ...profileQuery, enabled: me.isSuccess });
  const location = useLocation();
  if (me.isPending) {
    return <p className="p-6 text-slate-500">Loading...</p>;
  }
  if (me.isError) {
    return <Navigate to="/sign-in" replace />;
  }
  if (profile.isPending) {
    return <p className="p-6 text-slate-500">Loading profile...</p>;
  }
  if (profile.isError) {
    return <p className="p-6 text-red-600">Could not load your profile.</p>;
  }
  if (!profile.data.has_cv && location.pathname !== "/profile") {
    return <Navigate to="/profile" replace state={{ from: location }} />;
  }
  return <Outlet />;
}

export const router = createBrowserRouter([
  { path: "/sign-in", element: <SignIn /> },
  {
    element: <ProtectedRoute />,
    children: [
      { path: "/", element: <Home /> },
      { path: "/profile", element: <Profile /> },
      { path: "/sources", element: <Sources /> },
    ],
  },
]);
