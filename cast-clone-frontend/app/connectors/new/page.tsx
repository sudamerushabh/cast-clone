import { AddConnectorForm } from "@/components/connectors/AddConnectorForm";

export default function NewConnectorPage() {
  return (
    <div className="p-6">
      <h1 className="mb-6 text-2xl font-bold">Add Git Connector</h1>
      <AddConnectorForm />
    </div>
  );
}
