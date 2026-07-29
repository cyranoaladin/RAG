import { Routes, Route } from 'react-router'
import HomeClient from './app/HomeClient'

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<HomeClient />} />
    </Routes>
  )
}
