/** API 请求客户端 */
import axios from "axios"

const api = axios.create({
  baseURL: "/api",
})

export default api
