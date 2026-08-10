import type { Metadata } from "next";
import { redirect } from "next/navigation";

export const metadata: Metadata = {
  title: "Model Monitoring | SabiScore",
  description: "Authoritative settled-prediction model performance",
};

export default function MonitoringPage() {
  redirect("/performance");
}
