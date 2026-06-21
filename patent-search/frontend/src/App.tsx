import { BrowserRouter, Routes, Route, NavLink } from 'react-router-dom'
import SearchPage from './pages/SearchPage'
import ImportPage from './pages/ImportPage'
import SettingsPage from './pages/SettingsPage'
import './App.css'

/** 导航栏 */
function NavBar() {
  return (
    <nav style={{
      display: 'flex',
      alignItems: 'center',
      padding: '0 32px',
      height: '56px',
      backgroundColor: '#16213e',
      borderBottom: '1px solid #2a2a4a',
      boxShadow: '0 2px 8px rgba(0, 0, 0, 0.3)',
      position: 'sticky',
      top: 0,
      zIndex: 100,
    }}>
      {/* 应用标题/Logo区域 */}
      <div style={{
        fontSize: '20px',
        fontWeight: 700,
        color: '#4fc3f7',
        marginRight: '40px',
        letterSpacing: '1px',
        whiteSpace: 'nowrap',
        userSelect: 'none',
      }}>
        专利语义检索
      </div>

      {/* 导航链接区域 */}
      <div style={{
        display: 'flex',
        gap: '8px',
        alignItems: 'center',
      }}>
        {[
          { to: '/', end: true, label: '搜索' },
          { to: '/import', end: false, label: '导入' },
          { to: '/settings', end: false, label: '设置' },
        ].map(({ to, end, label }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            style={({ isActive }) => ({
              color: isActive ? '#4fc3f7' : '#a0a0b8',
              textDecoration: 'none',
              fontWeight: isActive ? 600 : 400,
              fontSize: '15px',
              padding: '8px 16px',
              borderRadius: '6px',
              backgroundColor: isActive ? 'rgba(79, 195, 247, 0.1)' : 'transparent',
              transition: 'all 0.2s ease',
            })}
          >
            {label}
          </NavLink>
        ))}
      </div>
    </nav>
  )
}

function App() {
  return (
    <BrowserRouter>
      <NavBar />
      <main style={{ padding: '24px 32px' }}>
        <Routes>
          <Route path="/" element={<SearchPage />} />
          <Route path="/import" element={<ImportPage />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Routes>
      </main>
    </BrowserRouter>
  )
}

export default App
