import os

frontend_dir = "/Users/vindhyaverma/RAZORPAY INTERNSHIP/merchantmind/frontend/src/app"

page_tsx = """
import Link from 'next/link';

export default function Home() {
  return (
    <main className="min-h-screen bg-gray-50 text-gray-900 p-8">
      <div className="max-w-4xl mx-auto">
        <header className="mb-10 flex justify-between items-center border-b pb-4">
          <h1 className="text-3xl font-bold text-indigo-700">MerchantMind</h1>
          <nav className="flex gap-4">
            <Link href="/" className="text-indigo-600 font-semibold">Shop</Link>
            <Link href="/policy" className="text-gray-500 hover:text-indigo-600">Policy</Link>
            <Link href="/transaction" className="text-gray-500 hover:text-indigo-600">Transaction</Link>
            <Link href="/audit" className="text-gray-500 hover:text-indigo-600">Audit</Link>
          </nav>
        </header>
        
        <div className="bg-white p-6 rounded-lg shadow-sm border border-gray-200">
          <h2 className="text-xl font-semibold mb-4">Shop via AI Agent</h2>
          <form className="flex gap-4 mb-8" onSubmit={(e) => e.preventDefault()}>
            <input 
              type="text" 
              placeholder="e.g., Order a birthday cake under ₹500" 
              className="flex-1 p-3 border rounded-md"
              defaultValue="Order a birthday cake under ₹500"
            />
            <button className="bg-indigo-600 text-white px-6 py-3 rounded-md font-medium hover:bg-indigo-700">
              Agent Checkout
            </button>
          </form>
          
          <div className="bg-gray-50 p-4 rounded-md border font-mono text-sm h-64 overflow-y-auto">
            <div className="text-gray-500 italic">Agent is idle...</div>
            {/* Live SSE or Audit polling will show steps here */}
          </div>
        </div>
      </div>
    </main>
  );
}
"""

with open(f"{frontend_dir}/page.tsx", "w") as f:
    f.write(page_tsx.strip())
