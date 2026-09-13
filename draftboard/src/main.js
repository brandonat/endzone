import { mount } from 'svelte'
import './app.css'
import DraftBoard from './DraftBoard.svelte'

const app = mount(DraftBoard, {
  target: document.getElementById('app'),
})

export default app
